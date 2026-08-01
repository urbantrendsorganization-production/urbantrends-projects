"""Every deposit figure the client sees comes out of `deposit_amount`.

These are unit tests with no database: the function is pure, and slice 6 will
push its output straight to M-Pesa.
"""

from decimal import Decimal

import pytest

from shops.money import DepositMode, deposit_amount, format_kes


def deposit(mode, value, price):
    return deposit_amount(mode=mode, value=value, price=price)


class TestNoDeposit:
    def test_mode_none_takes_nothing(self):
        assert deposit(DepositMode.NONE, None, 3500) == 0

    def test_a_free_service_takes_nothing(self):
        assert deposit(DepositMode.PERCENT, Decimal("25"), 0) == 0


class TestFlat:
    def test_flat_is_taken_verbatim(self):
        assert deposit(DepositMode.FLAT, Decimal("1000"), 3500) == 1000

    def test_flat_equal_to_the_price_is_allowed(self):
        assert deposit(DepositMode.FLAT, Decimal("500"), 500) == 500

    def test_flat_above_the_price_is_clamped(self):
        """A deposit larger than the bill is a refund waiting to happen. The
        model constraint rejects this too; the function does not rely on it."""
        assert deposit(DepositMode.FLAT, Decimal("5000"), 3500) == 3500


class TestPercent:
    def test_the_designs_own_example(self):
        """Screen 1 shows KES 3,500 with a KES 1,000 deposit — 28.6%. The
        default 25% of 3,500 is 875."""
        assert deposit(DepositMode.PERCENT, Decimal("25"), 3500) == 875

    def test_a_hundred_percent_is_the_whole_price(self):
        assert deposit(DepositMode.PERCENT, Decimal("100"), 3500) == 3500

    @pytest.mark.parametrize(
        "price,expected",
        [
            (1332, 333),  # 333.00 exactly
            (1333, 333),  # 333.25 rounds down
            (1334, 334),  # 333.50 rounds *up* — half-up, not banker's
            (1335, 334),  # 333.75 rounds up
            (1336, 334),  # 334.00 exactly
        ],
    )
    def test_rounding_is_half_up_at_the_quarter_shilling_boundary(self, price, expected):
        """25% puts the boundary on .25/.50/.75 increments, so this walks
        straight through the awkward cases. 1334 is the one that separates
        half-up from banker's rounding: banker's would give 334 here but 332 at
        1330 — the rule has to be the one a person applies in their head."""
        assert deposit(DepositMode.PERCENT, Decimal("25"), price) == expected

    def test_banker_s_rounding_would_disagree_and_we_do_not_use_it(self):
        """10% of 45 is 4.5. Half-up gives 5; banker's would give 4."""
        assert deposit(DepositMode.PERCENT, Decimal("10"), 45) == 5

    def test_float_arithmetic_would_disagree_and_we_do_not_use_it(self):
        """0.25 * 1333 in binary float is 333.2499999999999886, which rounds to
        333 by luck. 0.7 * 1000 is 699.9999999999999, which does not."""
        assert deposit(DepositMode.PERCENT, Decimal("0.7"), 100000) == 700
        assert int(round(0.7 / 100 * 100000)) == 700  # agrees here
        assert deposit(DepositMode.PERCENT, Decimal("29.7"), 1000) == 297

    def test_a_fractional_percentage_is_allowed(self):
        assert deposit(DepositMode.PERCENT, Decimal("12.5"), 2000) == 250

    def test_a_percentage_that_rounds_away_to_nothing_is_floored_at_one(self):
        """A KES 0 deposit is not a deposit — it is a free no-show, which is
        the thing this product exists to stop."""
        assert deposit(DepositMode.PERCENT, Decimal("1"), 20) == 1
        assert deposit(DepositMode.PERCENT, Decimal("0.5"), 10) == 1

    def test_the_floor_never_exceeds_the_price(self):
        """Both clamps at once: floor of 1, ceiling of price."""
        assert deposit(DepositMode.PERCENT, Decimal("1"), 1) == 1


class TestFormatting:
    @pytest.mark.parametrize(
        "amount,expected",
        [(0, "KES 0"), (875, "KES 875"), (1000, "KES 1,000"), (1500000, "KES 1,500,000")],
    )
    def test_money_is_grouped_and_never_abbreviated(self, amount, expected):
        """The design is explicit: always `KES 1,000`, never `1.5k`."""
        assert format_kes(amount) == expected


def test_an_unknown_mode_raises_rather_than_returning_zero():
    """Returning 0 would silently make a service free."""
    with pytest.raises(ValueError):
        deposit("half", Decimal("50"), 1000)
