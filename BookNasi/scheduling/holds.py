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
    check_can_hold(client, now=now)

    appointment = create_appointment(
        staff=staff,
        service=service,
        starts_at=starts_at,
        source=BookingSource.ONLINE,
        client=client,
        now=now,
        client_request_id=client_request_id,
    )
    schedule_release(appointment)
    return appointment


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
    return True
