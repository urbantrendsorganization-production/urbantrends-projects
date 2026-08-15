"""The headline, which is the one place this screen states a conclusion.

The design asks for "Deposits are working" rather than a metric. That is right —
an owner should not have to do arithmetic to know whether to renew — and it is
also the most dangerous string in the product, because it is the software making
a claim about the customer's business. So the *choice* is made in Python where
it can be tested, and only the wording lives on the client.

The ordering matters more than any individual branch: the "you are not taking
deposits" case has to be reached before anything encouraging, because a shop
with every service set to no-deposit is the shop that churns, and it is the one
that most easily looks fine on a quiet fortnight.
"""

from dataclasses import replace

import pytest

from reporting.metrics import (
    MIN_OUTCOMES_FOR_A_VERDICT,
    Clients,
    Money,
    Outcomes,
    Report,
    Verdict,
    verdict_for,
)
from reporting.period import Period
from reporting.tests.conftest import REPORT_WEDNESDAY


def build(*, outcomes, previous=None, money=None):
    return Report(
        period=Period(REPORT_WEDNESDAY, REPORT_WEDNESDAY),
        outcomes=outcomes,
        previous=previous or Outcomes(),
        money=money or Money(collected_kes=10_000),
        clients=Clients(),
    )


def rate(no_shows, completed):
    return Outcomes(completed=completed, no_show=no_shows)


class TestNotEnoughToSayAnything:
    def test_a_new_shop_gets_no_verdict(self):
        assert verdict_for(build(outcomes=rate(0, 3))) == Verdict.TOO_EARLY

    def test_the_threshold_is_on_finished_bookings_not_on_everything(self):
        """A fortnight of cancellations is not evidence about no-shows."""
        outcomes = Outcomes(completed=2, no_show=0, cancelled=90)

        assert verdict_for(build(outcomes=outcomes)) == Verdict.TOO_EARLY


class TestTheDepositWarningComesFirst:
    def test_a_shop_taking_no_deposits_is_told_so_however_good_its_numbers(self):
        """The most expensive sentence this product could print is an
        encouraging one to a shop that has switched the deposit off."""
        outcomes = rate(0, MIN_OUTCOMES_FOR_A_VERDICT)

        verdict = verdict_for(
            build(outcomes=outcomes, previous=rate(10, 40), money=Money(collected_kes=0))
        )

        assert verdict == Verdict.NO_DEPOSITS

    def test_a_shop_taking_deposits_is_judged_on_its_trend(self):
        outcomes = rate(1, MIN_OUTCOMES_FOR_A_VERDICT)

        assert verdict_for(build(outcomes=outcomes, previous=rate(10, 40))) != Verdict.NO_DEPOSITS


class TestTheTrend:
    def test_a_falling_no_show_rate_is_the_deposits_working(self):
        assert (
            verdict_for(build(outcomes=rate(2, 48), previous=rate(10, 40)))
            == Verdict.DEPOSITS_WORKING
        )

    def test_a_rising_rate_is_said_out_loud(self):
        assert (
            verdict_for(build(outcomes=rate(12, 38), previous=rate(2, 48)))
            == Verdict.NO_SHOWS_RISING
        )

    def test_a_rate_that_barely_moved_is_steady(self):
        """One bad Saturday is not a trend, and calling it one teaches an owner
        to stop reading the headline."""
        assert verdict_for(build(outcomes=rate(6, 44), previous=rate(5, 45))) == Verdict.STEADY

    def test_a_previous_period_with_too_little_in_it_is_not_compared_against(self):
        """A shop's first full month has a half-empty month behind it. Comparing
        against three bookings would produce a swing of tens of points from
        nothing."""
        built = build(outcomes=rate(2, 48), previous=Outcomes(completed=3))

        assert verdict_for(built) != Verdict.NO_SHOWS_RISING

    def test_forfeits_alone_are_a_result_when_there_is_nothing_to_compare(self):
        """No trend yet, but money the shop kept that would otherwise have been
        zero — CLAUDE.md §1. That is a real answer to "is this working"."""
        built = build(
            outcomes=rate(2, 48),
            previous=Outcomes(),
            money=Money(collected_kes=10_000, forfeited_kes=1_750),
        )

        assert verdict_for(built) == Verdict.DEPOSITS_WORKING

    def test_no_trend_and_no_forfeits_is_steady_rather_than_a_claim(self):
        built = build(outcomes=rate(2, 48), previous=Outcomes())

        assert verdict_for(built) == Verdict.STEADY


class TestItNeverDividesByNothing:
    @pytest.mark.parametrize(
        "outcomes,previous",
        [
            (Outcomes(), Outcomes()),
            (rate(0, 40), Outcomes(cancelled=9)),
            (Outcomes(cancelled=90), rate(4, 40)),
        ],
    )
    def test_every_empty_shape_still_produces_a_verdict(self, outcomes, previous):
        assert verdict_for(build(outcomes=outcomes, previous=previous)) in vars(Verdict).values()

    def test_the_report_property_and_the_function_agree(self):
        built = build(outcomes=rate(2, 48), previous=rate(10, 40))

        assert built.verdict == verdict_for(built)
        assert replace(built, outcomes=Outcomes()).verdict == Verdict.TOO_EARLY
