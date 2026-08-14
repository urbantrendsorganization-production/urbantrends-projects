"""Creating and releasing a hold. The whole of slice 5's write path.

A hold is a `pending_payment` appointment with an expiry. It occupies the slot
against the exclusion constraint exactly as a confirmed booking does — which is
the point, because the slot has to be genuinely gone while the client is off
finding their M-Pesa PIN — and it goes away on its own if nothing pays for it.

Slice 6 adds one thing to this file's world and nothing else: the STK push, and
a callback that moves `pending_payment` to `confirmed`. Everything around it
already exists here, including the release.

## Client identity

CLAUDE.md §12: no account, no OTP. The phone number typed at checkout is
matched to a `Client` on the **normalised** number, scoped to the organization —
so a regular who books at two branches of the same salon is one person with one
history (§3), and the same number at an unrelated salon is a separate record
under a separate controller (§9).

Normalisation happens before the lookup, not inside `Client.save()` alone:
`0712345678` and `+254712345678` typed at two different visits must not become
two people, and a `get_or_create` on the raw string would do exactly that.
"""

import logging
from contextvars import ContextVar
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.phone import normalize_phone
from clients.models import Client
from scheduling.abuse import check_can_hold
from scheduling.booking import create_appointment
from scheduling.statuses import AppointmentStatus, BookingSource

logger = logging.getLogger(__name__)


class ServiceNotPubliclyBookable(Exception):
    """CLAUDE.md §5, at the write path rather than only the read path.

    A deposit-free service is absent from the public service list, so a client
    never sees one. This is for the request that did not come from the UI.
    """


def client_for_phone(organization, phone, *, full_name=""):
    """The one place a public booking turns a number into a person.

    Returns the existing `Client` for this number at this organization, or
    creates one. Never duplicates: the unique constraint decides, and a race
    between two first-time bookings resolves by re-reading rather than by
    raising at the client.
    """
    normalised = normalize_phone(phone)
    existing = Client.objects.for_org(organization).filter(phone=normalised).first()
    if existing is not None:
        # A returning client keeps the name the shop already has. The booking
        # form does not ask for one, and overwriting a name a staff member
        # typed with a blank would be a silent data loss.
        return existing
    try:
        with transaction.atomic():
            return Client.objects.create(
                organization=organization, phone=normalised, full_name=full_name
            )
    except IntegrityError:
        # `one_client_per_phone_per_org`. Somebody else created it between the
        # read and the write; theirs is as good as ours.
        return Client.objects.for_org(organization).get(phone=normalised)


def create_hold(*, shop, service, staff, starts_at, phone, now=None, client_request_id=None):
    """Hold `starts_at` for the number that asked for it, or raise.

    Raises `ServiceNotPubliclyBookable`, `HoldRefused` (see `abuse.py`),
    `SlotUnavailable` or `SlotTaken`. Nothing here catches those — the view
    turns each into its own status code, because "you have too many holds",
    "that time was never bookable" and "somebody beat you by 200ms" are three
    different things to say to a client.
    """
    now = now or timezone.now()

    # §5 enforced at the API, not only in the UI. Without a deposit there is no
    # STK push, without a push there is no phone verification, and an unverified
    # number holding a slot for free is precisely what this rule prevents.
    if not service.is_publicly_bookable:
        raise ServiceNotPubliclyBookable(service.name)

    client = client_for_phone(shop.organization, phone)
    check_can_hold(client, staff=staff, now=now)

    appointment = create_appointment(
        staff=staff,
        service=service,
        starts_at=starts_at,
        source=BookingSource.ONLINE,
        client=client,
        now=now,
        client_request_id=client_request_id,
    )
    # The manage link, minted with the booking rather than with the
    # confirmation SMS. CLAUDE.md §12: "the link is the session" — and the
    # session has to exist before the message that carries it is rendered, which
    # happens inside the payment callback.
    from scheduling import manage_tokens

    manage_tokens.issue(appointment, now=now)

    # Slice 7. Credit is spent before the push, not after, so the STK prompt
    # carries the amount actually owed. Pushing the full deposit and refunding
    # the credit afterwards would take money we have already been given and
    # hand it back through a channel we do not control.
    apply_credit(appointment, now=now)

    schedule_release(appointment)
    return appointment


def apply_credit(appointment, *, now=None):
    """Spend any shop credit this client holds against this booking's deposit.

    Returns what is still owed to M-Pesa, and writes it to `deposit_snapshot` so
    every downstream reader — the STK push, the confirm screen, the balance
    line — sees one figure rather than each doing its own subtraction.

    A credit that covers the deposit entirely leaves nothing to push, which is
    the case CLAUDE.md §5's carve-out exists for: the credit descends from a
    succeeded payment made from this number, so the booking is verified even
    though no prompt goes out for it. See `payments/credit.py`.
    """
    from payments import credit as credit_module

    now = now or timezone.now()
    owed = appointment.deposit_snapshot
    if owed < 1 or appointment.client_id is None:
        return owed

    applied = credit_module.redeem(
        client=appointment.client,
        shop=appointment.shop,
        appointment=appointment,
        amount_kes=owed,
        now=now,
    )
    if applied < 1:
        return owed

    appointment.deposit_snapshot = owed - applied
    appointment.save(update_fields=["deposit_snapshot", "updated_at"])
    return appointment.deposit_snapshot


def schedule_release(appointment):
    """Queue the per-appointment release and remember its id.

    The task is for *timeliness* — it fires within a second of expiry, so the
    slot comes back while the next client is still looking at the page. It is
    not what makes release correct; `tasks.sweep_expired_holds` is. Losing the
    broker, losing the worker, or losing this row's task id all cost a minute,
    not a permanently held slot.
    """
    from scheduling.tasks import release_expired_hold

    if appointment.hold_expires_at is None:
        return appointment
    result = release_expired_hold.apply_async(
        args=[str(appointment.pk)], eta=appointment.hold_expires_at
    )
    appointment.hold_release_task_id = result.id
    appointment.save(update_fields=["hold_release_task_id", "updated_at"])
    return appointment


#: Set while a release task is running, so the transition it performs does not
#: turn around and try to revoke the task that is performing it.
_releasing = ContextVar("booknasi_releasing_hold", default=False)


def cancel_scheduled_release(task_id, *, appointment_id=None):
    """Revoke the release task once the hold is resolved.

    Best-effort by design. The task re-reads the row before it does anything, so
    a revoke that fails — a broker blip, a worker that already dequeued it —
    costs nothing. What would be expensive is the opposite: relying on the
    revoke and letting the task act without re-checking.

    Takes the id rather than the appointment, because by the time this runs the
    column has been cleared — the row must not carry a task id that no longer
    means anything.

    Called from `transitions.apply_transition` after the commit, never directly.
    """
    if not task_id or _releasing.get():
        return
    try:
        from config.celery import app

        app.control.revoke(task_id)
    except Exception:  # noqa: BLE001 — a failed revoke is not a failed booking
        logger.warning("could not revoke hold release for %s", appointment_id)


def grace_ceiling(appointment):
    """The hard limit past which a hold is released whatever M-Pesa is doing.

    `hold_expires_at + HOLD_GRACE_MINUTES`. Derived, never stored, and that is
    the point: the ceiling is a fixed distance from a timestamp that nothing
    moves, so it extends **once** and cannot be pushed out by a resend, a retry
    or a second push. There is no code path that can lengthen it, because there
    is no column to lengthen.
    """
    if appointment.hold_expires_at is None:
        return None
    return appointment.hold_expires_at + timedelta(minutes=settings.HOLD_GRACE_MINUTES)


def hold_is_releasable(appointment, *, now=None):
    """Should the slot go back on offer yet?

    Slice 6's one change to the hold lifecycle, and the mechanism the client
    picked for `slotLost`: shrink the population rather than service it.

    A hold whose STK push is still outstanding is **not** released the instant
    its TTL runs out. Safaricom is often a few seconds late and sometimes a
    minute late, and releasing at exactly `hold_expires_at` manufactures the
    worst state this product has — the client's money left, the slot went to
    somebody else, and nobody did anything wrong. The grace window costs the
    next client up to two minutes of a slot that was probably about to be paid
    for anyway; the alternative costs somebody their money and their booking.

    Bounded, and bounded in the strongest available way: see `grace_ceiling`.
    """
    now = now or timezone.now()
    if appointment.hold_expires_at is None or appointment.hold_expires_at > now:
        return False

    ceiling = grace_ceiling(appointment)
    if ceiling is not None and now < ceiling and payment_outstanding_for(appointment):
        return False
    return True


def payment_outstanding_for(appointment):
    """Is there an STK push against this hold that Safaricom has not answered?

    Imported late and deliberately: `payments` depends on `scheduling` through a
    foreign key, so the arrow at import time has to go the other way. One lazy
    import here is cheaper than a signal, a registry or a hook, and it is
    greppable — which a registry is not.
    """
    from payments.machine import awaiting_result_for

    return awaiting_result_for(appointment).exists()


def release_hold(appointment, *, now=None, expired=True):
    """Give the slot back. Idempotent, and safe to call from anywhere.

    A thin wrapper over the transition table rather than a second status write —
    see `transitions.apply_transition`, which is the only function that sets
    `Appointment.status`.

    `expired=False` is a client pressing cancel, and is deliberately not counted
    by `abuse.py`.

    Returns True if this call was the one that released it.
    """
    from scheduling.transitions import apply_transition

    now = now or timezone.now()
    if appointment.status != AppointmentStatus.PENDING_PAYMENT:
        # Already paid, already cancelled, already swept. Not an error: the
        # per-appointment task and the sweep can both arrive, and a callback
        # that landed a second before either is the case this exists for.
        return False

    token = _releasing.set(True)
    try:
        apply_transition(appointment, AppointmentStatus.CANCELLED, now=now, expired_hold=expired)
    finally:
        _releasing.reset(token)

    if expired:
        _tell_them_the_hold_went(appointment)
    return True


def _tell_them_the_hold_went(appointment):
    """One SMS when a hold runs out. Slice 6.

    Not cosmetic. The design's screen 8 tells a client their slot was released,
    and a client who closed the page never sees it — they find out at the shop,
    which is the same experience as a double booking from where they are
    standing. A client who pressed cancel gets nothing: they already know.

    Lazy import for the same reason as `payment_outstanding_for` above.
    """
    from notifications.service import queue_message
    from notifications.templates import Template

    if appointment.source != BookingSource.ONLINE:
        return
    if payment_outstanding_for(appointment):
        # Past the grace ceiling with a push still live. The slot genuinely goes
        # back on offer — that part is right — but this message says "Nothing
        # was taken from your M-Pesa", and we do not know that. If the late
        # callback then lands, the client is holding an SMS that contradicts the
        # confirmation (or the slot-lost notice) that follows it. Silence here;
        # the settlement path sends whichever message turns out to be true.
        return
    queue_message(appointment, Template.HOLD_RELEASED)


def confirm_credit_covered(appointment, *, now=None):
    """Confirm a booking whose deposit was met entirely by shop credit.

    CLAUDE.md §5's carve-out, and the only path that confirms a public booking
    without an STK push. The rule it appears to break says a deposit-free public
    booking is an unverified number holding a slot; this number is verified, by
    the succeeded payment the credit descends from. §5 states that rather than
    leaving it to be re-derived here.

    Goes through `apply_transition` with `Actor.SYSTEM`, like every other
    money-driven confirmation — the transition table stays the only writer of
    `Appointment.status`, and `SlotTaken` still means what it means.
    """
    from scheduling.transitions import Actor, apply_transition

    now = now or timezone.now()
    apply_transition(appointment, AppointmentStatus.CONFIRMED, now=now, actor=Actor.SYSTEM)

    from notifications.service import queue_message
    from notifications.templates import Template

    queue_message(appointment, Template.BOOKING_CONFIRMED)
    return appointment
