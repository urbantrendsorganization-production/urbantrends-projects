"""Export and erasure. CLAUDE.md §9, thirteen slices late.

§9 names four obligations and says any feature touching client data must keep
them working: a stated retention period, an export path, a delete path, and the
processor clause honoured. The last is a contract rather than code. The other
three are here.

## Erasure is a scrub, never a cascade

§9 says so outright — "soft-delete with PII scrub, not a cascade" — and the
reason is that a client's rights and a shop's books are different people's
data. Deleting the row would take the appointments with it, and with them the
revenue figures, the no-show rate and the utilisation the owner dashboard is
built on. One person exercising their rights would silently rewrite somebody
else's accounts, and a shop would have no way of knowing why last quarter
changed.

So the appointment rows stay and the person leaves them — and, deliberately,
they go on pointing at the same client row. It is scrubbed, not deleted, which
is precisely what §9 asks for: "must not orphan appointment records in a way
that breaks reporting". Nulling the link would orphan them, and the repeat-
client rate on the owner dashboard would quietly lose every visit an erased
person ever made.

`Appointment.client` is `SET_NULL` and `Credit.client` is `PROTECT`, and
neither fires here, because nothing is deleted. Both guard the other case: an
admin or a shell removing a client row outright.

## What is actually removed

Everything that identifies a person, everywhere it is held:

- `full_name`, `phone` and `notes` on the client row
- the payer's `phone` on every `Payment`, which is a second copy of the number
  and the one most easily forgotten — it is on a table nobody thinks of as
  personal data
- every live manage token, revoked, because a token is a session and an erased
  person should not have one

There is deliberately no appointment-level name to scrub. A walk-in with a name
and no number gets its own `Client` row (`scheduling/views.py`), so the person
is in exactly one place and an erasure has one place to reach. That is worth
knowing precisely: had the name been snapshotted onto the appointment as well,
this module would have had to find it there too, and the copy nobody remembers
is the copy that survives an erasure.

What stays: money, times, statuses, service and staff. None of it identifies
anybody once the above is gone, and all of it is the shop's own record of its
own trade.

## Credit is voided, and the caller is told first

A credit is redeemed by pushing to a phone number. Erase the number and the
credit cannot be spent, so pretending otherwise would be holding money for
somebody we have made unreachable. `plan_for` returns the amount so the screen
can say it before anybody presses anything, and `CreditState.VOIDED_ON_ERASURE`
keeps it distinct from a shop voiding a credit by hand — the shop did not
decide this and should not appear to have.

## Retention

`RETENTION_MONTHS` after the last appointment, swept by
`clients.tasks.scrub_expired_clients`. Twenty-four months: long enough that a
twice-a-year regular is never lost, short enough to be a real limit. A client
with no appointments at all is measured from `created_at`, so a record created
by a booking that never completed does not live forever.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Max, Q, Sum
from django.utils import timezone

from clients.models import Client, ScrubReason

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Consequence:
    """What erasing this client will cost, before it happens.

    Returned by `plan_for` so a confirm screen can state it. The two numbers are
    the ones somebody would be upset to discover afterwards: money that stops
    being spendable, and history that stops having a name on it.
    """

    appointments: int
    credit_kes: int
    already_erased: bool


def plan_for(client):
    """What `erase` would do. Reads only."""
    from payments.credit import Credit, CreditState

    live = (
        Credit.objects.unscoped()
        .filter(client=client, state=CreditState.OPEN)
        .aggregate(total=Sum("remaining_kes"))["total"]
        or 0
    )
    return Consequence(
        appointments=client.appointments.count(),
        credit_kes=live,
        already_erased=client.is_erased,
    )


@transaction.atomic
def erase(client, *, reason=ScrubReason.SHOP, now=None):
    """Remove the person, keep the trade. Idempotent.

    Idempotent because the three ways in — an owner pressing the button, the
    retention sweep, and a re-run after a partial failure — can all arrive at a
    row that is already done, and the second attempt must not be an error that
    somebody has to interpret.
    """
    now = now or timezone.now()
    if client.is_erased:
        return client

    _scrub_payments(client)
    _revoke_tokens(client)
    _void_credit(client, now=now)

    client.full_name = ""
    client.phone = ""
    client.notes = ""
    client.scrubbed_at = now
    client.scrub_reason = reason
    # The request flag is deliberately kept. It is the audit trail: a controller
    # asked to show it acted on a request needs to be able to point at both the
    # ask and the action, and clearing it would leave only the action.
    client.save(
        update_fields=[
            "full_name",
            "phone",
            "notes",
            "scrubbed_at",
            "scrub_reason",
            "updated_at",
        ]
    )

    # Id and reason only. Logging a count of what was scrubbed would be fine;
    # logging anything that was scrubbed would defeat the point, and §5 already
    # forbids phone numbers in logs.
    logger.info("client %s erased (%s)", client.id, reason)
    return client


def _scrub_payments(client):
    """The payer's number, on every payment for every one of their bookings.

    The copy most easily missed. `Payment.phone` is on a table nobody thinks of
    as holding personal data, and it is the number Safaricom pushed to — so an
    erasure that stopped at the client row would leave the phone number in the
    money records, which are the ones kept longest.
    """
    from payments.models import Payment

    Payment.objects.unscoped().filter(appointment__client=client).update(phone="")


def _revoke_tokens(client):
    """A manage link is a session. An erased person should not have one.

    Left live, the link in an old SMS would still open a booking page — and
    although the page would no longer show a name, the token would still be a
    working credential belonging to somebody who asked to be forgotten.
    """
    from scheduling.manage_tokens import revoke_for_client

    revoke_for_client(client)


def _void_credit(client, *, now):
    """Unspent balances stop being spendable, and say why.

    Redemption pushes to a phone number. Once there is no number the credit
    cannot be reached, so leaving it `OPEN` would be a liability on the shop's
    books that can never be discharged and never be spent.
    """
    from payments.credit import Credit, CreditState

    Credit.objects.unscoped().filter(client=client, state=CreditState.OPEN).update(
        state=CreditState.VOIDED_ON_ERASURE, updated_at=now
    )


# ---------------------------------------------------------------- retention


def retention_cutoff(now=None):
    now = now or timezone.now()
    # `timedelta` in days rather than a month-arithmetic dependency. CLAUDE.md
    # §11: no dependency for what the stdlib does, and a retention boundary that
    # lands a day either side of a calendar month is not a boundary anybody can
    # tell the difference at.
    return now - timedelta(days=30 * settings.CLIENT_RETENTION_MONTHS)


def expired_clients(now=None):
    """Clients whose last activity is older than the retention period.

    Last *appointment*, falling back to `created_at`. The fallback matters: a
    client row created by a booking that never completed has no appointments,
    and measured on appointments alone it would be kept forever — which is the
    opposite of a retention policy, applied to the records with the least reason
    to exist.
    """
    cutoff = retention_cutoff(now)
    return (
        Client.objects.unscoped()
        .filter(scrubbed_at__isnull=True)
        # `time_range__startswith` is the lower bound of the range column, not
        # a string prefix. `Appointment.starts_at` is a Python property over
        # `time_range` (there is no such column), so aggregating on it is an
        # ORM error rather than a slow query — and the error names `startswith`
        # in a way that reads like a typo, which is worth the comment.
        .annotate(last_seen=Max("appointments__time_range__startswith"))
        .filter(Q(last_seen__lt=cutoff) | Q(last_seen__isnull=True, created_at__lt=cutoff))
    )


# ------------------------------------------------------------------ export


def export_for(client):
    """Everything held about one person, as plain data.

    JSON rather than CSV: the DPA calls for a commonly-used, machine-readable
    form, and this is nested — appointments with their payments — which a single
    CSV cannot express without either flattening money onto every row or
    shipping four files.

    Includes the erased case on purpose. Somebody asking what is held after an
    erasure should get a truthful answer that says *what is left and why*,
    rather than a 404 that reads as evasion.
    """
    from scheduling.models import Appointment

    appointments = (
        Appointment.objects.unscoped()
        .filter(client=client)
        .select_related("service", "staff", "shop")
        .prefetch_related("payments")
        .order_by("time_range")
    )

    return {
        "exported_at": timezone.now().isoformat(),
        "organization": client.organization.name,
        "client": {
            "id": str(client.id),
            "full_name": client.full_name,
            "phone": client.phone,
            "notes": client.notes,
            "first_seen": client.created_at.isoformat(),
            "erased": client.is_erased,
            "erased_at": client.scrubbed_at.isoformat() if client.scrubbed_at else None,
        },
        "retention": {
            "months_after_last_visit": settings.CLIENT_RETENTION_MONTHS,
            "statement": retention_statement(),
        },
        "appointments": [
            {
                "id": str(row.id),
                "shop": row.shop.name,
                "service": row.service.name if row.service_id else None,
                "staff": row.staff.display_name if row.staff_id else None,
                "starts_at": row.starts_at.isoformat(),
                "status": row.status,
                "price_kes": row.price_snapshot,
                "deposit_kes": row.deposit_snapshot,
                "payments": [
                    {
                        "support_code": payment.support_code,
                        "amount_kes": payment.amount,
                        "state": payment.state,
                        "mpesa_receipt": payment.mpesa_receipt,
                        "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
                    }
                    for payment in row.payments.all()
                ],
            }
            for row in appointments
        ],
        "credits": [
            {
                "amount_kes": credit.amount_kes,
                "remaining_kes": credit.remaining_kes,
                "state": credit.state,
                "expires_at": credit.expires_at.isoformat() if credit.expires_at else None,
            }
            for credit in client.credits.all()
        ],
    }


def retention_statement():
    """The sentence a client reads, worded once.

    Same rule as `money.refundSentence` in §12: a policy that is worded in two
    places is a policy a shop can state one way to a client and another way in
    its own settings.
    """
    months = settings.CLIENT_RETENTION_MONTHS
    return (
        f"Your name, phone number and visit history are kept for {months} months "
        "after your last appointment, then permanently removed. Your bookings stay "
        "in the shop's records with your details taken out. You can ask for removal "
        "at any time."
    )
