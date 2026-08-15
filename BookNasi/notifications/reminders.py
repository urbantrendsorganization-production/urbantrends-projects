"""Scheduled messages. The half of §6 that slices 6 and 7 deliberately deferred.

A confirmation is a *reaction*: a transition fires, a message goes, it is done.
A reminder is *scheduled*, which means something has to hold a promise about the
future and then be right about whether the future still wants it. CLAUDE.md §6
is blunt about the failure mode — "clients getting reminded about appointments
that no longer exist is a trust bug, not a cosmetic one" — and that is the whole
design pressure here.

## Two reminders, and why not one

§6 says T-24h and T-2h and prices three messages a booking. §8's MVP list says
"confirmation + one reminder". The two lines disagreed; settled at slice 8
planning in favour of §6, with the qualification that makes them nearly agree
anyway: **a reminder whose moment has already passed is never armed.** A booking
made six hours out gets only the T-2h, and one made ninety minutes out gets
neither. Same-day bookings are common, so the realised average is well under
three.

The two do different jobs and that is why both survive:

- **T-24h** buys the *shop* something. A client who cancels on it frees a slot
  that can still be resold. Under §12's policy it is also the last moment a
  cancellation is refundable rather than credit, which is the honest reason to
  send it.
- **T-2h** buys the *client* something. It is the one that stops somebody simply
  forgetting, which is what a no-show usually is.

## Safe to lose, safe to run twice

The same rule `scheduling/tasks.py` states for hold release, for the same
reason. Each reminder is a row plus an `eta` task: the task is for timeliness,
`sweep_due_reminders` is for correctness, and a lost broker costs minutes rather
than a message nobody sends. Revoking on cancel is an optimisation — `fire`
re-reads the appointment and refuses to message a booking that is no longer
active, so a revoke that never lands costs nothing.

The sweep also *creates* rows it finds missing, which is what makes this
self-healing rather than dependent on every confirmation path remembering to
call in.

## The 07:00 floor

Only the T-2h can land antisocially. A T-24h fires at the appointment's own
wall-clock time, so it is inside trading hours by construction; a T-2h for an
08:00 appointment is 06:00, which is an SMS to a stranger before they are up.
Those shift forward to 07:00 rather than being dropped — a late reminder is
worth more than none — and never past the appointment itself, which would make
it a notification about something already happening.
"""

import logging
from datetime import time, timedelta

from django.db import models
from django.utils import timezone

from core.models import OrgDerivedModel
from notifications.templates import Template

logger = logging.getLogger(__name__)

#: EAT. One timezone, no abstraction layer — CLAUDE.md §4.
from scheduling.availability import LOCAL_TZ  # noqa: E402

#: Nothing is sent before this, local time. See the module docstring.
QUIET_UNTIL = time(7, 0)

#: How far ahead an `eta` task is actually armed.
#:
#: A Celery `eta` weeks out is a promise held in a worker's memory for weeks: it
#: is lost on every restart, it occupies prefetch, and a shop with a month of
#: bookings would have thousands of them queued to buy precision nobody can
#: perceive. So the `eta` task exists only for the last stretch, and everything
#: beyond it is the sweep's — which runs every five minutes and is what makes
#: the whole thing correct anyway.
#:
#: A reminder five minutes late is still a reminder. That is the difference
#: between this and hold release, where five minutes is a slot somebody could
#: not book, and it is why that one arms an `eta` however far out it is.
ETA_HORIZON = timedelta(hours=1)


class ReminderKind(models.TextChoices):
    T24 = "t24", "24 hours before"
    T2 = "t2", "2 hours before"


#: How far ahead of the appointment each one fires, and which template it uses.
#: One mapping, so a third reminder is a row here rather than a search.
OFFSETS = {
    ReminderKind.T24: timedelta(hours=24),
    ReminderKind.T2: timedelta(hours=2),
}
TEMPLATES = {
    ReminderKind.T24: Template.REMINDER_24H,
    ReminderKind.T2: Template.REMINDER_2H,
}


class Reminder(OrgDerivedModel):
    """One promise to message somebody at a particular moment.

    Deliberately **not** a `Message`. A `Message` is one row per send we
    attempted and is immutable evidence; this is a mutable schedule that a
    reschedule moves and a cancellation deletes. Collapsing them would mean
    either rewriting the audit trail on every move, or keeping a queued row
    around that looks like a message that failed to send.

    `sent_at` is cleared when `send_at` moves, which is what lets a booking
    rescheduled after its 24-hour reminder already went get a fresh one for its
    new date — the case `notifications/migrations/0001_initial.py` had in mind
    when it kept reminders out of `ONE_SHOT`.
    """

    org_source = "appointment"

    appointment = models.ForeignKey(
        "scheduling.Appointment", on_delete=models.CASCADE, related_name="reminders"
    )
    kind = models.CharField(max_length=8, choices=ReminderKind.choices)
    send_at = models.DateTimeField()
    #: Best-effort revocation, exactly as `Appointment.hold_release_task_id` is.
    #: Losing it costs a worker wake-up, never a wrong message.
    task_id = models.CharField(max_length=64, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "reminders"
        ordering = ["send_at"]
        constraints = [
            # One live reminder of each kind per booking. A retried schedule, a
            # sweep running beside an `eta` task, and a double confirmation all
            # land on the same row rather than making a second one.
            models.UniqueConstraint(
                fields=["appointment", "kind"], name="one_reminder_of_each_kind"
            ),
        ]
        indexes = [
            # The sweep's query: due, unsent.
            models.Index(fields=["sent_at", "send_at"], name="reminder_due_idx"),
        ]

    def __str__(self):
        when = f"{self.send_at:%Y-%m-%d %H:%M}"
        return f"{self.get_kind_display()} for {self.appointment_id} at {when}"


# ------------------------------------------------------------ when to send


def due_at(appointment, kind):
    """The instant this reminder should go, clamped out of the small hours."""
    raw = appointment.starts_at - OFFSETS[kind]
    local = raw.astimezone(LOCAL_TZ)
    if local.time() >= QUIET_UNTIL:
        return raw

    floor = local.replace(hour=QUIET_UNTIL.hour, minute=QUIET_UNTIL.minute, second=0, microsecond=0)
    shifted = floor.astimezone(raw.tzinfo)
    # Never past the appointment itself: a reminder that arrives while the
    # client is in the chair is not a reminder.
    return min(shifted, appointment.starts_at)


# --------------------------------------------------------------- scheduling


def ensure_scheduled(appointment, *, now=None):
    """Arm both reminders for this booking. Idempotent, and safe to re-run.

    Called from the transition that confirms a booking, from `reschedule`, and
    from the sweep — the last of which is what makes a forgotten call site a
    delay rather than a silence.

    Returns the reminders that are live afterwards.
    """
    from scheduling.statuses import ACTIVE_STATUSES, BookingSource

    now = now or timezone.now()
    if appointment.status not in ACTIVE_STATUSES:
        return []
    if appointment.source == BookingSource.WALK_IN or appointment.client_id is None:
        # Nobody to message, and they are already in the chair.
        return []

    live = []
    for kind in ReminderKind:
        when = due_at(appointment, kind)
        if when <= now:
            # The moment has passed. A booking made six hours out never arms its
            # T-24h; one made ninety minutes out arms neither. This is the whole
            # of the difference between §6's three-message estimate and what a
            # shop actually pays.
            continue
        live.append(_arm(appointment, kind, when))
    return live


def _arm(appointment, kind, when):
    from notifications.tasks import send_reminder

    reminder, created = Reminder.objects.unscoped().get_or_create(
        appointment=appointment, kind=kind, defaults={"send_at": when}
    )
    if not created and reminder.send_at != when:
        # The booking moved. A new moment is a new promise, so any previous send
        # is forgotten — see the class docstring.
        reminder.send_at = when
        reminder.sent_at = None
        reminder.save(update_fields=["send_at", "sent_at", "updated_at"])
    elif not created and reminder.sent_at is not None:
        return reminder  # already went, and the moment has not moved

    if reminder.send_at <= timezone.now() + ETA_HORIZON:
        result = send_reminder.apply_async(args=[str(reminder.pk)], eta=reminder.send_at)
        Reminder.objects.unscoped().filter(pk=reminder.pk).update(task_id=result.id)
    return reminder


def cancel_for(appointment):
    """Drop every promise attached to this booking, and try to revoke the tasks.

    §6's trust bug, closed. The revoke is best-effort and the delete is not:
    `fire` refuses to message an inactive booking anyway, so the row going away
    is belt and the status re-check is braces.
    """
    rows = list(Reminder.objects.unscoped().filter(appointment=appointment))
    for reminder in rows:
        _revoke(reminder.task_id, reminder_id=reminder.pk)
    Reminder.objects.unscoped().filter(appointment=appointment).delete()
    return len(rows)


def _revoke(task_id, *, reminder_id=None):
    if not task_id:
        return
    try:
        from config.celery import app

        app.control.revoke(task_id)
    except Exception:  # noqa: BLE001 — an optimisation, never a correctness step
        logger.warning("could not revoke reminder task for %s", reminder_id)


# ------------------------------------------------------------- sending


def should_send(appointment, *, now=None):
    """Whether this booking still wants to be reminded about.

    The re-check that makes a lost revoke harmless. Cancelled, completed,
    already started or marked no-show all mean silence.
    """
    from scheduling.statuses import AppointmentStatus

    now = now or timezone.now()
    if appointment.status not in (AppointmentStatus.CONFIRMED, AppointmentStatus.PENDING_PAYMENT):
        return False
    # A booking that has already begun does not need telling about.
    return appointment.starts_at > now


def send(reminder, *, now=None):
    """Send one reminder if it is still wanted. Returns a short verb."""
    from notifications.service import queue_message

    now = now or timezone.now()
    appointment = reminder.appointment

    if reminder.sent_at is not None:
        return "already-sent"
    if not should_send(appointment, now=now):
        # The ordinary case for a cancelled booking whose revoke was lost.
        Reminder.objects.unscoped().filter(pk=reminder.pk).delete()
        return "no-longer-wanted"

    queue_message(appointment, TEMPLATES[ReminderKind(reminder.kind)])
    Reminder.objects.unscoped().filter(pk=reminder.pk).update(sent_at=now, updated_at=now)
    return "sent"


def due_reminders(*, now=None, limit=500):
    """Everything whose moment has arrived and which has not gone yet."""
    now = now or timezone.now()
    return (
        Reminder.objects.unscoped()
        .filter(sent_at__isnull=True, send_at__lte=now)
        .select_related("appointment", "appointment__shop", "appointment__staff")
        .order_by("send_at")[:limit]
    )


def arm_imminent(*, now=None, limit=500):
    """Give an `eta` task to reminders that have come inside the horizon.

    The other half of `ETA_HORIZON`. A reminder armed weeks ago has a row and no
    task; this is what gives it one shortly before it is due, so the last hour
    is precise without the broker holding a month of promises.

    Idempotent: a reminder that already has a task id is left alone.
    """
    from notifications.tasks import send_reminder

    now = now or timezone.now()
    coming = Reminder.objects.unscoped().filter(
        sent_at__isnull=True, task_id="", send_at__gt=now, send_at__lte=now + ETA_HORIZON
    )[:limit]
    armed = 0
    for reminder in coming:
        result = send_reminder.apply_async(args=[str(reminder.pk)], eta=reminder.send_at)
        Reminder.objects.unscoped().filter(pk=reminder.pk).update(task_id=result.id)
        armed += 1
    return armed


def backfill_missing(*, now=None, horizon_hours=48, limit=200):
    """Arm reminders for confirmed bookings that have none.

    The self-healing half. Every confirmation path is supposed to call
    `ensure_scheduled`, and one of them will eventually not — a new endpoint, a
    data import, a bulk fix run from a shell. This makes that a delay of one
    sweep interval rather than a client who is never reminded.

    Bounded to the next `horizon_hours` because a booking six weeks out has
    nothing to arm yet that the sweep will not catch nearer the time.
    """
    from scheduling.models import Appointment
    from scheduling.statuses import AppointmentStatus, BookingSource

    now = now or timezone.now()
    candidates = (
        Appointment.objects.unscoped()
        .filter(
            status__in=(AppointmentStatus.CONFIRMED, AppointmentStatus.PENDING_PAYMENT),
            time_range__startswith__gt=now,
            time_range__startswith__lte=now + timedelta(hours=horizon_hours),
            source=BookingSource.ONLINE,
            client__isnull=False,
        )
        .exclude(reminders__isnull=False)
        .select_related("shop", "staff", "client")[:limit]
    )
    armed = 0
    for appointment in candidates:
        if ensure_scheduled(appointment, now=now):
            armed += 1
    return armed
