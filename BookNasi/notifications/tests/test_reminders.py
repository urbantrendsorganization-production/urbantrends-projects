"""Reminders: armed, moved, dropped, and never sent to the wrong person.

CLAUDE.md §6 names the failure this file exists to prevent — "clients getting
reminded about appointments that no longer exist is a trust bug, not a cosmetic
one" — so the cancellation and reschedule cases get more attention here than the
happy path does.

The §6-versus-§8 conflict was settled at slice 8 planning in favour of two
reminders, with the qualification that a reminder whose moment has passed is
never armed. `TestWhatGetsArmed` is where that lives.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from notifications import reminders
from notifications.models import Message
from notifications.reminders import Reminder, ReminderKind
from notifications.templates import Template
from scheduling.availability import LOCAL_TZ
from scheduling.holds import create_hold
from scheduling.statuses import AppointmentStatus
from scheduling.tests.conftest import WEDNESDAY, eat

pytestmark = pytest.mark.django_db

S = AppointmentStatus


@pytest.fixture(autouse=True)
def not_eager(settings):
    """Reminders are the one thing eager Celery cannot model.

    `apply_async(eta=...)` under `CELERY_TASK_ALWAYS_EAGER` ignores the `eta`
    and runs *now*, so every reminder would fire the moment it was armed and
    these tests would assert on a program nobody runs. With eager off the task
    is queued and nothing consumes it, which is exactly the state the sweep and
    the explicit `send` calls below are written to exercise.

    `Message` rows are still created synchronously by `queue_message`, so
    everything asserted here is unaffected.
    """
    settings.CELERY_TASK_ALWAYS_EAGER = False


def booking_at(shop_setup, hour, *, now, phone="0712345678", staff=None):
    return create_hold(
        shop=shop_setup.shop,
        service=shop_setup.braids,
        staff=staff or shop_setup.wanjiku,
        starts_at=eat(WEDNESDAY, hour),
        phone=phone,
        now=now,
    )


def pay(appointment, *, now=None):
    from payments.callbacks import handle_callback
    from payments.stk import initiate_push
    from payments.tests.conftest import stk_callback

    payment = initiate_push(appointment, now=now)
    handle_callback(stk_callback(payment.checkout_request_id), now=now)
    appointment.refresh_from_db()
    return payment


@pytest.fixture
def confirmed(shop_setup):
    """A paid booking at 10:00, made three days out — both reminders armed."""
    made_at = eat(WEDNESDAY, 10) - timedelta(days=3)
    appointment = booking_at(shop_setup, 10, now=made_at)
    pay(appointment, now=made_at)
    appointment.refresh_from_db()
    return appointment


def kinds_for(appointment):
    return set(
        Reminder.objects.unscoped().filter(appointment=appointment).values_list("kind", flat=True)
    )


class TestWhatGetsArmed:
    def test_a_booking_made_days_ahead_gets_both(self, confirmed):
        assert kinds_for(confirmed) == {ReminderKind.T24, ReminderKind.T2}

    def test_they_are_armed_at_the_right_moments(self, confirmed):
        rows = {r.kind: r for r in Reminder.objects.unscoped().filter(appointment=confirmed)}

        assert rows[ReminderKind.T24].send_at == confirmed.starts_at - timedelta(hours=24)
        assert rows[ReminderKind.T2].send_at == confirmed.starts_at - timedelta(hours=2)

    def test_a_same_day_booking_skips_the_24_hour_one(self, shop_setup):
        """The qualification that nearly reconciles §6 and §8. A booking made
        six hours out has no 24-hour reminder to send, so it never costs one."""
        made_at = eat(WEDNESDAY, 10) - timedelta(hours=6)
        appointment = booking_at(shop_setup, 10, now=made_at)
        pay(appointment, now=made_at)

        assert kinds_for(appointment) == {ReminderKind.T2}

    def test_a_last_minute_booking_gets_neither(self, shop_setup):
        made_at = eat(WEDNESDAY, 10) - timedelta(minutes=90)
        appointment = booking_at(shop_setup, 10, now=made_at)
        pay(appointment, now=made_at)

        assert kinds_for(appointment) == set()

    def test_a_walk_in_gets_none(self, shop_setup):
        """No stored number, no manage link, and they are already in the chair."""
        from scheduling.booking import create_appointment
        from scheduling.statuses import BookingSource

        walk_in = create_appointment(
            staff=shop_setup.wanjiku,
            service=shop_setup.braids,
            starts_at=eat(WEDNESDAY, 16),
            source=BookingSource.WALK_IN,
            now=eat(WEDNESDAY, 10),
        )

        assert kinds_for(walk_in) == set()

    def test_arming_twice_does_not_duplicate(self, confirmed):
        """The sweep and the `eta` path both call in. A second row would be a
        second SMS, which the client pays for in attention and we pay for in
        credibility."""
        reminders.ensure_scheduled(confirmed)
        reminders.ensure_scheduled(confirmed)

        assert Reminder.objects.unscoped().filter(appointment=confirmed).count() == 2


class TestTheQuietFloor:
    def test_an_early_appointment_does_not_text_at_six(self):
        """A T-2h for an 08:00 booking is 06:00. Shifted to 07:00, not dropped —
        a late reminder beats none.

        Exercised against `due_at` directly rather than a real booking: the
        fixture shop's stylists start at 09:00 EAT, so no bookable appointment
        can produce a pre-07:00 reminder — which is the good news, and also why
        a test that went through `create_hold` would silently assert nothing.
        """
        appointment = _stub_starting_at(eat(WEDNESDAY, 8))

        when = reminders.due_at(appointment, ReminderKind.T2)

        assert when.astimezone(LOCAL_TZ).hour == 7
        assert when > appointment.starts_at - timedelta(hours=2)

    def test_the_24_hour_one_is_never_clamped(self, confirmed):
        """It fires at the appointment's own wall-clock time, so it is inside
        trading hours by construction."""
        when = reminders.due_at(confirmed, ReminderKind.T24)

        assert when == confirmed.starts_at - timedelta(hours=24)

    @pytest.mark.parametrize("hour", [7, 8, 9])
    def test_it_never_lands_after_the_appointment(self, hour):
        """A reminder that arrives while the client is in the chair is not a
        reminder. A 07:00 booking's T-2h would clamp to 07:00 — the start."""
        appointment = _stub_starting_at(eat(WEDNESDAY, hour))

        for kind in ReminderKind:
            assert reminders.due_at(appointment, kind) <= appointment.starts_at


def _stub_starting_at(when):
    """The minimum `due_at` reads. Pure function, no row needed."""
    return type("Stub", (), {"starts_at": when})()


class TestCancellationKillsThem:
    """§6's trust bug, from three directions."""

    def test_cancelling_drops_the_rows(self, confirmed):
        from scheduling.lifecycle import cancel

        cancel(confirmed, now=confirmed.starts_at - timedelta(days=2))

        assert kinds_for(confirmed) == set()

    def test_a_reminder_that_survives_still_refuses_to_send(self, confirmed):
        """The re-check that makes a lost revoke harmless.

        The row is deleted on cancel and the broker task is revoked, and both of
        those can fail. This is the third line: `send` re-reads the appointment
        and will not message a booking that is no longer active.
        """
        reminder = Reminder.objects.unscoped().filter(appointment=confirmed).first()
        from scheduling.transitions import apply_transition

        apply_transition(confirmed, S.CANCELLED, now=confirmed.starts_at - timedelta(days=2))
        confirmed.refresh_from_db()
        # Put the row back, as a lost delete would have.
        reminder.pk = None
        reminder.sent_at = None
        reminder.save()
        reminder.refresh_from_db()

        outcome = reminders.send(reminder, now=confirmed.starts_at - timedelta(hours=23))

        assert outcome == "no-longer-wanted"
        assert (
            not Message.objects.unscoped()
            .filter(appointment=confirmed, template=Template.REMINDER_24H)
            .exists()
        )

    def test_a_completed_booking_is_not_reminded(self, confirmed):
        from scheduling.transitions import apply_transition

        apply_transition(confirmed, S.IN_PROGRESS, now=confirmed.starts_at)
        apply_transition(confirmed, S.COMPLETED, now=confirmed.starts_at + timedelta(hours=4))

        assert kinds_for(confirmed) == set()


class TestRescheduleMovesThem:
    def test_the_new_date_gets_its_own_reminders(self, confirmed):
        """A booking moved from Wednesday to a week later must not keep
        Wednesday's reminders — that is the trust bug with extra steps."""
        from scheduling.lifecycle import reschedule

        target = eat(WEDNESDAY, 12) + timedelta(days=7)
        reschedule(confirmed, starts_at=target, now=confirmed.starts_at - timedelta(days=2))
        confirmed.refresh_from_db()

        rows = {r.kind: r for r in Reminder.objects.unscoped().filter(appointment=confirmed)}
        assert rows[ReminderKind.T24].send_at == target - timedelta(hours=24)
        assert rows[ReminderKind.T2].send_at == target - timedelta(hours=2)

    def test_a_move_re_arms_a_reminder_that_had_already_gone(self, confirmed):
        """The case `0001_initial` kept reminders out of `ONE_SHOT` for. The
        Wednesday 24-hour notice went; the new date needs its own."""
        from scheduling.lifecycle import reschedule

        row = Reminder.objects.unscoped().get(appointment=confirmed, kind=ReminderKind.T24)
        row.sent_at = timezone.now()
        row.save(update_fields=["sent_at"])

        target = eat(WEDNESDAY, 12) + timedelta(days=7)
        reschedule(confirmed, starts_at=target, now=confirmed.starts_at - timedelta(days=2))

        row.refresh_from_db()
        assert row.sent_at is None, "a new moment is a new promise"
        assert row.send_at == target - timedelta(hours=24)

    def test_no_duplicate_rows_after_several_moves(self, confirmed):
        from scheduling.lifecycle import reschedule

        when = confirmed.starts_at - timedelta(days=2)
        for hour in (12, 13):
            reschedule(confirmed, starts_at=eat(WEDNESDAY, hour), now=when)
            confirmed.refresh_from_db()

        assert Reminder.objects.unscoped().filter(appointment=confirmed).count() == 2


class TestSending:
    def test_a_due_reminder_sends_and_is_stamped(self, confirmed, console_messages):
        reminder = Reminder.objects.unscoped().get(appointment=confirmed, kind=ReminderKind.T2)

        assert reminders.send(reminder, now=reminder.send_at) == "sent"

        reminder.refresh_from_db()
        assert reminder.sent_at is not None
        assert (
            Message.objects.unscoped()
            .filter(appointment=confirmed, template=Template.REMINDER_2H)
            .exists()
        )

    def test_sending_twice_sends_one_message(self, confirmed, console_messages):
        reminder = Reminder.objects.unscoped().get(appointment=confirmed, kind=ReminderKind.T2)

        reminders.send(reminder, now=reminder.send_at)
        reminder.refresh_from_db()
        assert reminders.send(reminder, now=reminder.send_at) == "already-sent"

        assert (
            Message.objects.unscoped()
            .filter(appointment=confirmed, template=Template.REMINDER_2H)
            .count()
            == 1
        )

    def test_the_24_hour_message_carries_the_manage_link(self, confirmed, console_messages):
        """The most useful thing a 24-hour reminder can produce is a
        cancellation while the slot is still resellable."""
        reminder = Reminder.objects.unscoped().get(appointment=confirmed, kind=ReminderKind.T24)
        reminders.send(reminder, now=reminder.send_at)

        message = Message.objects.unscoped().get(
            appointment=confirmed, template=Template.REMINDER_24H
        )
        assert confirmed.manage_token in message.variables["link"]

    def test_the_sweep_sends_what_the_eta_task_lost(self, confirmed, console_messages):
        from notifications.tasks import sweep_due_reminders

        Reminder.objects.unscoped().filter(appointment=confirmed).update(
            send_at=timezone.now() - timedelta(minutes=5)
        )

        results = sweep_due_reminders()

        assert results["sent"] == 2

    def test_the_sweep_arms_a_booking_that_was_never_armed(self, shop_setup, console_messages):
        """The self-healing half. A confirmation path that forgets to call
        `ensure_scheduled` costs one sweep interval, not a silent client."""
        made_at = timezone.now()
        appointment = booking_at(shop_setup, 10, now=made_at)
        # Drag it forward so it is inside the backfill horizon, then strip the
        # reminders as a forgetful call site would have left it.
        appointment.time_range = _shift(appointment, timezone.now() + timedelta(hours=30))
        appointment.save(update_fields=["time_range"])
        Reminder.objects.unscoped().filter(appointment=appointment).delete()
        appointment.status = S.CONFIRMED
        appointment.save(update_fields=["status"])

        armed = reminders.backfill_missing(now=timezone.now())

        assert armed == 1
        assert kinds_for(appointment)


def _shift(appointment, new_start):
    from django.db.backends.postgresql.psycopg_any import DateTimeTZRange

    from scheduling.models import RANGE_BOUNDS

    length = appointment.ends_at - appointment.starts_at
    return DateTimeTZRange(new_start, new_start + length, RANGE_BOUNDS)


class TestTheNoShowMessage:
    def test_a_forfeited_no_show_is_told(self, confirmed, console_messages):
        """§12 puts the terms before payment; this is the sentence that says the
        rule just cost them KES 875."""
        from scheduling.transitions import apply_transition

        apply_transition(confirmed, S.NO_SHOW, now=confirmed.starts_at + timedelta(minutes=20))

        message = Message.objects.unscoped().get(appointment=confirmed, template=Template.NO_SHOW)
        assert "875" in message.variables["paid"]

    def test_an_unpaid_no_show_says_nothing(self, shop_setup, console_messages):
        """ "You missed it and we kept KES 0" is worse than silence."""
        from scheduling.transitions import apply_transition

        appointment = booking_at(shop_setup, 10, now=eat(WEDNESDAY, 10) - timedelta(days=2))
        apply_transition(appointment, S.CANCELLED, now=eat(WEDNESDAY, 10))
        appointment.refresh_from_db()

        assert (
            not Message.objects.unscoped()
            .filter(appointment=appointment, template=Template.NO_SHOW)
            .exists()
        )

    def test_it_is_one_shot(self, confirmed, console_messages):
        """You can only miss an appointment once. A staff member toggling the
        status back and forth must not send it twice."""
        from scheduling.transitions import apply_transition

        after = confirmed.starts_at + timedelta(minutes=20)
        apply_transition(confirmed, S.NO_SHOW, now=after)
        apply_transition(confirmed, S.CONFIRMED, now=after)
        apply_transition(confirmed, S.NO_SHOW, now=after)

        assert (
            Message.objects.unscoped()
            .filter(appointment=confirmed, template=Template.NO_SHOW)
            .count()
            == 1
        )
