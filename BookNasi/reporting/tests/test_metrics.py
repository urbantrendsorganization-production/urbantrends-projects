"""The counting rules, each one asserted where it can be argued with.

Every test here corresponds to a sentence in `reporting/metrics.py`'s docstring.
That is the point: an owner who disagrees with a number should be able to find
the rule, and the rule should have a test that fails if somebody changes it by
accident.
"""

from datetime import timedelta

import pytest

from payments.credit import CreditSource, issue
from payments.states import PaymentState
from reporting.metrics import build_report
from reporting.tests.conftest import REPORT_WEDNESDAY
from scheduling.statuses import AppointmentStatus, BookingSource

pytestmark = pytest.mark.django_db

S = AppointmentStatus


@pytest.fixture
def report(shop_setup, report_period, now):
    def _report(period=None):
        return build_report(
            organization=shop_setup.organization,
            shops=[shop_setup.shop],
            period=period or report_period,
            now=now,
        )

    return _report


class TestWhichBookingsBelongToThePeriod:
    def test_a_booking_is_counted_on_the_day_it_starts(self, record, report, report_period):
        record(day=report_period.starts_on, hour=10)
        record(day=report_period.ends_on, hour=10)

        assert report().outcomes.completed == 2

    def test_a_booking_the_day_before_the_range_is_not_counted(self, record, report, report_period):
        record(day=report_period.starts_on - timedelta(days=1), hour=10)

        assert report().outcomes.completed == 0

    def test_an_overnight_booking_belongs_to_the_day_it_began(self, record, report, report_period):
        """The last evening of the range, running past local midnight into a day
        outside it. Counted once, here — `__overlap` would have counted its
        whole price in a period it mostly did not happen in."""
        record(day=report_period.ends_on, hour=22, minutes=240)

        assert report().outcomes.completed == 1


class TestTheOutcomeBuckets:
    def test_they_are_exhaustive(self, record, report, report_period):
        """`total` has to reconcile, or an owner cannot check the screen against
        their own diary."""
        record(hour=9, status=S.COMPLETED)
        record(hour=11, status=S.NO_SHOW)
        record(hour=13, status=S.CANCELLED)
        record(hour=15, status=S.CONFIRMED)
        record(day=report_period.ends_on, hour=9, status=S.CONFIRMED)

        outcomes = report().outcomes

        assert (outcomes.completed, outcomes.no_show, outcomes.cancelled) == (1, 1, 1)
        assert (outcomes.unresolved, outcomes.upcoming) == (1, 1)
        assert outcomes.total == 5

    def test_a_past_booking_still_confirmed_is_unresolved_not_completed(self, record, report):
        """Nobody pressed Finish. It earns nothing and it is published as its
        own number, because it means the rest of the screen understates."""
        record(hour=9, status=S.CONFIRMED)

        assert report().outcomes.unresolved == 1
        assert report().revenue_kes == 0

    def test_a_future_booking_is_upcoming_not_unresolved(self, record, report, report_period):
        record(day=report_period.ends_on, hour=9, status=S.CONFIRMED)

        assert report().outcomes.upcoming == 1
        assert report().outcomes.unresolved == 0


class TestTheNoShowRate:
    def test_it_is_no_shows_over_finished_bookings(self, record, report):
        for hour in (9, 11, 13):
            record(hour=hour, status=S.COMPLETED)
        record(hour=15, status=S.NO_SHOW)

        assert report().outcomes.no_show_rate == pytest.approx(0.25)

    def test_cancellations_are_outside_the_denominator(self, record, report):
        """A client who cancels told the shop, which is the behaviour §12's
        credit rule exists to encourage. Counting them here would make a shop
        look worse for the thing it wants more of."""
        for hour in (9, 11, 13):
            record(hour=hour, status=S.COMPLETED)
        record(hour=15, status=S.NO_SHOW)
        for hour in (16, 17):
            record(hour=hour, status=S.CANCELLED)

        assert report().outcomes.no_show_rate == pytest.approx(0.25)

    def test_it_is_null_rather_than_zero_when_nothing_has_finished(self, record, report):
        """The most flattering possible lie to tell a new customer would be
        0 %. A shop with no finished bookings has an *unknown* rate."""
        record(hour=9, status=S.CANCELLED)

        assert report().outcomes.no_show_rate is None

    def test_the_previous_period_is_measured_the_same_way(self, record, report, report_period):
        earlier = report_period.previous
        record(day=earlier.ends_on, hour=9, status=S.NO_SHOW)
        record(day=earlier.ends_on, hour=11, status=S.COMPLETED)
        record(hour=9, status=S.COMPLETED)

        built = report()

        assert built.previous.no_show_rate == pytest.approx(0.5)
        assert built.outcomes.no_show_rate == pytest.approx(0.0)


class TestRevenueIsBilledNotBanked:
    def test_revenue_is_the_price_of_completed_work(self, record, report):
        record(hour=9, price=3500, status=S.COMPLETED)
        record(hour=11, price=500, status=S.COMPLETED)

        assert report().revenue_kes == 4000

    def test_a_no_show_earns_nothing(self, record, report):
        record(hour=9, price=3500, status=S.NO_SHOW)

        assert report().revenue_kes == 0

    def test_deposits_are_a_separate_column_from_revenue(self, record, paid, report):
        """They must never be added together: one is what the shop charged, the
        other is the part of it we can prove arrived."""
        appointment = record(hour=9, price=3500, deposit=875, status=S.COMPLETED)
        paid(appointment, amount=875)

        built = report()

        assert built.revenue_kes == 3500
        assert built.money.collected_kes == 875

    def test_a_deposit_that_never_completed_is_not_collected(self, record, paid, report):
        appointment = record(hour=9, status=S.COMPLETED)
        paid(appointment, amount=875, state=PaymentState.FAILED)

        assert report().money.collected_kes == 0


class TestTheForfeit:
    def test_a_no_show_deposit_is_forfeited(self, record, paid, report):
        """CLAUDE.md §1: money that used to be zero."""
        appointment = record(hour=9, status=S.NO_SHOW)
        paid(appointment, amount=875)

        assert report().money.forfeited_kes == 875

    def test_a_completed_booking_forfeits_nothing(self, record, paid, report):
        paid(record(hour=9, status=S.COMPLETED), amount=875)

        assert report().money.forfeited_kes == 0

    def test_a_booking_that_issued_credit_is_not_a_forfeit(
        self, record, paid, client_row, report, shop_setup
    ):
        """Matching `lifecycle.is_forfeited`. A late cancellation becomes credit
        and the shop has not kept the money outright — counting it as a forfeit
        would overstate the product's own headline number, in the direction
        nobody would question."""
        client = client_row()
        appointment = record(hour=9, status=S.NO_SHOW, client=client)
        payment = paid(appointment, amount=875)
        issue(
            appointment=appointment,
            payment=payment,
            amount_kes=875,
            source=CreditSource.LATE_CANCELLATION,
        )

        assert report().money.forfeited_kes == 0

    def test_a_second_credit_does_not_double_count_the_deposit(
        self, record, paid, client_row, report
    ):
        """The `Exists` in `_money`, asserted. A join to `credits_issued` would
        have added this booking's deposit to `collected_kes` once per credit."""
        client = client_row()
        appointment = record(hour=9, status=S.COMPLETED, client=client)
        payment = paid(appointment, amount=875)
        for _ in range(2):
            issue(
                appointment=appointment,
                payment=payment,
                amount_kes=100,
                source=CreditSource.SHOP_GOODWILL,
            )

        assert report().money.collected_kes == 875


class TestRepeatClients:
    def test_a_client_with_an_earlier_visit_is_a_repeat(
        self, record, report, client_row, report_period
    ):
        amina = client_row("Amina")
        record(day=report_period.previous.ends_on, hour=9, client=amina)
        record(hour=9, client=amina)

        built = report()

        assert (built.clients.seen, built.clients.repeat) == (1, 1)
        assert built.clients.repeat_rate == pytest.approx(1.0)

    def test_a_first_visit_is_not(self, record, report, client_row):
        record(hour=9, client=client_row("Njeri"))

        built = report()

        assert (built.clients.seen, built.clients.repeat) == (1, 0)

    def test_two_visits_inside_the_period_do_not_make_a_repeat(self, record, report, client_row):
        """The earlier visit has to predate the period. Otherwise every client
        who came twice in a busy month counts as a returning regular, and the
        rate measures frequency rather than retention."""
        amina = client_row("Amina")
        record(hour=9, client=amina)
        record(hour=11, client=amina)

        assert report().clients.repeat == 0

    def test_walk_ins_without_a_client_lower_the_attributed_share(self, record, report, client_row):
        """The honesty column. On a walk-in-heavy shop the repeat rate is a
        statement about the booked half of the trade, and the screen has to be
        able to say so."""
        record(hour=9, client=client_row("Amina"))
        for hour in (11, 13, 15):
            record(hour=hour, source=BookingSource.WALK_IN)

        built = report()

        assert built.clients.completed == 4
        assert built.clients.attributed == 1
        assert built.clients.attributed_share == pytest.approx(0.25)


class TestTheStaffTable:
    def test_every_active_stylist_gets_a_row_even_with_no_work(self, report, shop_setup):
        """An empty line is information. Dropping it would hide exactly the
        person an owner most needs to see."""
        rows = {row.display_name for row in report().staff}

        assert rows == {"Wanjiku", "Grace"}

    def test_rows_are_ordered_by_revenue(self, record, report, shop_setup):
        record(staff=shop_setup.grace, hour=9, price=3500)
        record(staff=shop_setup.wanjiku, hour=9, price=500)

        assert [row.display_name for row in report().staff] == ["Grace", "Wanjiku"]

    def test_revenue_and_deposits_are_attributed_to_the_stylist_who_did_the_work(
        self, record, paid, report, shop_setup
    ):
        paid(record(staff=shop_setup.grace, hour=9, price=3500), amount=875)

        rows = {row.display_name: row for row in report().staff}

        assert (rows["Grace"].revenue_kes, rows["Grace"].deposits_kes) == (3500, 875)
        assert (rows["Wanjiku"].revenue_kes, rows["Wanjiku"].deposits_kes) == (0, 0)

    def test_a_no_show_occupies_the_chair_for_utilisation(
        self, record, report, shop_setup, report_period
    ):
        """High utilisation with low revenue is a no-show problem, and the table
        can only say so if the no-show's hour counts as booked. A cancellation
        does not: the slot went back on sale."""
        record(staff=shop_setup.grace, hour=9, minutes=60, status=S.NO_SHOW)
        record(staff=shop_setup.grace, hour=11, minutes=60, status=S.CANCELLED)

        grace = next(row for row in report().staff if row.display_name == "Grace")

        assert grace.booked_minutes == 60

    def test_utilisation_is_booked_over_available(self, record, report, shop_setup):
        record(staff=shop_setup.grace, hour=9, minutes=180)
        grace = next(row for row in report().staff if row.display_name == "Grace")

        # The fixture rosters 09:00-18:00 Monday-Saturday. The ten-day period
        # covers nine trading days.
        assert grace.capacity_minutes == 9 * 9 * 60
        assert grace.utilisation == pytest.approx(180 / (9 * 9 * 60))

    def test_utilisation_is_null_when_nobody_rostered_them(self, report, shop_setup):
        from shops.models import WorkingHours

        WorkingHours.objects.for_org(shop_setup.organization).filter(
            staff=shop_setup.grace
        ).delete()
        grace = next(row for row in report().staff if row.display_name == "Grace")

        assert grace.capacity_minutes == 0
        assert grace.utilisation is None

    def test_shortened_walk_ins_are_reported_next_to_the_number_they_distort(
        self, record, report, shop_setup
    ):
        """`Appointment.was_shortened`'s own comment asks for this: a stylist
        who shortens under pressure books fewer minutes at the same price, which
        flatters revenue-per-hour and deflates utilisation."""
        record(staff=shop_setup.grace, hour=9, minutes=30, was_shortened=True)

        grace = next(row for row in report().staff if row.display_name == "Grace")

        assert grace.shortened == 1


class TestTenantIsolation:
    def test_another_organizations_work_is_invisible(self, record, report, rival_shop, shop_setup):
        """Almost every isolation bug is invisible in a single-tenant fixture."""
        from scheduling.models import Appointment
        from scheduling.tests.conftest import eat

        starts_at = eat(REPORT_WEDNESDAY, 10)
        Appointment.objects.create(
            shop=rival_shop.shop,
            staff=rival_shop.wanjiku,
            service=rival_shop.braids,
            time_range=(starts_at, starts_at + timedelta(hours=1)),
            status=S.COMPLETED,
            source=BookingSource.ONLINE,
            price_snapshot=9999,
            deposit_snapshot=0,
            duration_snapshot=60,
        )
        record(hour=12, price=3500)

        built = report()

        assert built.revenue_kes == 3500
        assert built.outcomes.completed == 1
        assert all("Sharp Cuts" not in row.shop_name for row in built.staff)
