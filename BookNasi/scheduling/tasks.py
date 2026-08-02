"""The first real Celery tasks in the project.

Two of them, and the relationship between them is the design:

- `release_expired_hold` is scheduled per appointment with an `eta`. It is for
  **timeliness** — the slot comes back within a second of expiry, while the next
  client is still looking at the page.
- `sweep_expired_holds` runs every minute from Beat. It is for **correctness**.

That split is deliberate. An `eta` task is a promise held in one broker; brokers
restart, workers are redeployed mid-queue, and a task id stored on a row can be
lost by any write that does not carry it. If release depended only on the
scheduled task, every one of those becomes a slot held forever, which on a
booking product is indistinguishable from a double-booking to the client who
cannot have it. With the sweep, all of them cost at most one minute.

The corollary, and the rule for anything added here later: **the scheduled task
must be safe to lose and safe to run twice.** Both re-read the row and both go
through `holds.release_hold`, which no-ops unless the appointment is still
`pending_payment`. Revoking is an optimisation on top of that, never a
correctness mechanism — see `holds.cancel_scheduled_release`.

Never log a phone number here. CLAUDE.md §5 is about M-Pesa payloads
specifically, but a worker log is exactly the place a number leaks into a file
nobody is thinking about; appointment ids are enough to trace with.
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from scheduling.models import Appointment
from scheduling.statuses import AppointmentStatus

logger = logging.getLogger(__name__)

#: How far back the sweep looks. Anything older than this and still
#: `pending_payment` is a row the sweep has already failed to release many
#: times over, and re-scanning a month of them every minute buys nothing —
#: the index range is what keeps this cheap on a shop with a year of history.
SWEEP_LOOKBACK_HOURS = 48


@shared_task(name="scheduling.release_expired_hold")
def release_expired_hold(appointment_id):
    """Release one hold, if it is still a hold.

    Scheduled with an `eta` at `hold_expires_at`. Re-reads and re-checks
    everything, so it is harmless when the appointment was paid for, cancelled
    or swept in the meantime — which is the ordinary case, not the exception.
    """
    from scheduling.holds import release_hold

    # `.unscoped()`, the sanctioned escape from the tenant guard: a worker has
    # no request and therefore no organization, and the appointment id is what
    # it was given. Scoped by the id itself, and it touches one row.
    appointment = Appointment.objects.unscoped().filter(pk=appointment_id).first()
    if appointment is None:
        # Deleted between scheduling and firing. Nothing to release.
        return "gone"
    if appointment.status != AppointmentStatus.PENDING_PAYMENT:
        return "resolved"
    if appointment.hold_expires_at and appointment.hold_expires_at > timezone.now():
        # Fired early — a clock skew between web and worker, or a re-delivery.
        # Leaving it alone is correct: the sweep will take it a minute after it
        # genuinely expires, and releasing a live hold would take a slot from a
        # client who is mid-payment.
        return "not-yet"

    released = release_hold(appointment, expired=True)
    if released:
        logger.info("released expired hold %s", appointment_id)
    return "released" if released else "resolved"


@shared_task(name="scheduling.sweep_expired_holds")
def sweep_expired_holds():
    """The backstop. Every minute, from Beat.

    Deliberately dumb: one indexed query, then the same `release_hold` the
    scheduled task uses. No batching cleverness, because the working set is
    "holds that expired in the last minute" and on any real shop that is a
    handful of rows.
    """
    now = timezone.now()
    # Deliberately cross-tenant: expired holds are released for every shop on
    # the box, and a sweep that had to be told which organization to look at
    # would be a sweep somebody forgets to run for a new tenant.
    stale = Appointment.objects.unscoped().filter(
        status=AppointmentStatus.PENDING_PAYMENT,
        hold_expires_at__lte=now,
        hold_expires_at__gte=now - timedelta(hours=SWEEP_LOOKBACK_HOURS),
    )
    from scheduling.holds import release_hold

    count = 0
    for appointment in stale:
        if release_hold(appointment, now=now, expired=True):
            count += 1
    if count:
        logger.info("sweep released %s expired holds", count)
    return count
