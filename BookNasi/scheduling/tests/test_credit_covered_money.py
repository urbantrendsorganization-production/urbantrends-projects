"""What a booking paid with shop credit tells the client about money.

Slice 11's manual walk booked a KES 1,200 service whose KES 300 deposit was
covered by credit the client already held, and was then told three different
things at once:

* the booked screen led with **"KES 0 received"**,
* the confirmation SMS said **"Paid KES 0 deposit. Balance KES 1,200 at the
  shop."** — the full price, in the one message a client keeps, after they had
  just spent KES 300 of their own money,
* and the manage page printed **"Total 1,200 · Deposit paid 300 · Balance
  1,200"** on a single card, which does not add up in any arithmetic.

One cause, three copies. `deposit_snapshot` is not the deposit the booking
carries: after `holds.apply_credit` it is *what is still owed to M-Pesa*, which
is exactly zero when credit covered the whole deposit. Three separate places
each wrote `price_snapshot - deposit_snapshot` and got a balance that billed the
client for money already handed over. The manage page's `paid` line was already
reading `lifecycle.paid_deposit_for` and was right, which is why one card could
contradict itself.

Nothing here tests the payment path. `deposit_snapshot` keeps its meaning —
`stk.py`, `repoint.py` and §5's carve-out in `public_api/views.py` all need
"what is still pushable" and all still read it. What changed is that the
figures shown to a *client* come from `paid_deposit_for` and `balance_due_for`,
which count spent credit as well as M-Pesa.

The partial case is here on purpose. Full coverage is the one that broke, but a
deposit split between credit and a card of cash is the one where a subtraction
that looks nearly right stays nearly right, and nobody notices until a client
argues about a bill.
"""

import pytest

from payments import credit as credit_module
from payments.models import Payment
from payments.states import PaymentState
from scheduling.holds import confirm_credit_covered, create_hold
from scheduling.lifecycle import balance_due_for, paid_deposit_for
from scheduling.statuses import AppointmentStatus
from scheduling.tests.conftest import eat

pytestmark = [pytest.mark.django_db, pytest.mark.loadbearing]

PHONE = "+254712345678"

#: The fixture braid: KES 3,500 at 25%.
PRICE = 3500
DEPOSIT = 875


@pytest.fixture
def held(shop_setup, wednesday, early):
    """A first booking, only so there is something for a credit to descend from."""
    return create_hold(
        shop=shop_setup.shop,
        service=shop_setup.braids,
        staff=shop_setup.wanjiku,
        starts_at=eat(wednesday, 10, 0),
        phone=PHONE,
        now=early,
    )


def _book_with_credit(shop_setup, wednesday, early, held, credit_kes):
    """Give the client `credit_kes`, then book a braid against a second chair.

    A different stylist for the second hold because the per-client hold ceiling
    is scoped per stylist, and tripping it here would fail this test for a
    reason that has nothing to do with money.
    """
    credit_module.issue(appointment=held, payment=None, amount_kes=credit_kes, now=early)
    booking = create_hold(
        shop=shop_setup.shop,
        service=shop_setup.braids,
        staff=shop_setup.grace,
        starts_at=eat(wednesday, 11, 0),
        phone=PHONE,
        now=early,
    )
    # What the view does next, and it matters to every figure here: a deposit
    # credit covered outright leaves nothing to push, so the booking confirms
    # immediately instead of waiting for a callback. Leaving it PENDING_PAYMENT
    # would test a state this path never reaches, and `balance_due_for`
    # deliberately reads differently while a deposit is still in flight.
    if booking.deposit_snapshot < 1:
        confirm_credit_covered(booking, now=early)
        booking.refresh_from_db()
    return booking


class TestCreditCoveringTheWholeDeposit:
    def test_the_snapshot_goes_to_zero_and_that_is_correct(
        self, shop_setup, wednesday, early, held
    ):
        """The premise the rest of the file rests on. Nothing is owed to M-Pesa,
        so no prompt goes out — CLAUDE.md §5's carve-out."""
        booking = _book_with_credit(shop_setup, wednesday, early, held, DEPOSIT)

        assert booking.deposit_snapshot == 0

    def test_the_deposit_is_reported_as_paid_not_as_nothing(
        self, shop_setup, wednesday, early, held
    ):
        booking = _book_with_credit(shop_setup, wednesday, early, held, DEPOSIT)

        assert paid_deposit_for(booking) == DEPOSIT

    def test_the_balance_is_the_price_less_what_was_paid(self, shop_setup, wednesday, early, held):
        """The defect in one line: this used to be `PRICE - 0`."""
        booking = _book_with_credit(shop_setup, wednesday, early, held, DEPOSIT)

        assert balance_due_for(booking) == PRICE - DEPOSIT

    def test_the_three_figures_agree_with_each_other(self, shop_setup, wednesday, early, held):
        """What the manage page could not do: add up.

        Asserted as a relationship rather than as three constants, because the
        bug was never a wrong constant — it was two figures on one card derived
        from different ideas of what had been paid."""
        booking = _book_with_credit(shop_setup, wednesday, early, held, DEPOSIT)

        assert paid_deposit_for(booking) + balance_due_for(booking) == booking.price_snapshot

    def test_the_confirmation_sms_names_the_real_figures(self, shop_setup, wednesday, early, held):
        """The message the client keeps. This said "Paid KES 0 deposit. Balance
        KES 3,500" — and no push had gone out to contradict it, because the
        credit is why there was no push."""
        from notifications.service import variables_for
        from notifications.templates import Template

        booking = _book_with_credit(shop_setup, wednesday, early, held, DEPOSIT)
        variables = variables_for(booking, Template.BOOKING_CONFIRMED)

        assert variables["paid"] == f"{DEPOSIT:,}"
        assert variables["balance"] == f"{PRICE - DEPOSIT:,}"

    def test_the_serializer_the_paid_screen_reads(self, shop_setup, wednesday, early, held):
        """`deposit_kes` stays what it is — the pushable figure — and the two
        new fields are what a client is shown. The screen fell back to
        `deposit_kes` precisely because `payment` is null on this path."""
        from public_api.serializers import PublicHoldSerializer

        booking = _book_with_credit(shop_setup, wednesday, early, held, DEPOSIT)
        data = PublicHoldSerializer(booking).data

        assert data["paid_kes"] == DEPOSIT
        assert data["balance_kes"] == PRICE - DEPOSIT
        assert data["deposit_kes"] == 0
        assert data["payment"] is None


class TestCreditCoveringPartOfIt:
    def test_the_remainder_is_still_owed_to_mpesa(self, shop_setup, wednesday, early, held):
        booking = _book_with_credit(shop_setup, wednesday, early, held, 400)

        assert booking.deposit_snapshot == DEPOSIT - 400

    def test_paid_counts_both_halves_once_the_push_succeeds(
        self, shop_setup, wednesday, early, held
    ):
        """Credit and cash, added once each. The failure mode worth guarding is
        double-counting: `deposit_snapshot` plus redemptions would report 875
        here too, by coincidence, and would be wrong the moment a push fails."""
        booking = _book_with_credit(shop_setup, wednesday, early, held, 400)
        Payment.objects.create(
            appointment=booking,
            amount=booking.deposit_snapshot,
            phone=PHONE,
            state=PaymentState.SUCCEEDED,
            support_code="BK-TEST01",
            # `succeeded_payment_has_a_receipt` — a success with nothing to
            # quote back to Safaricom is not a success anyone can reconcile.
            mpesa_receipt="SJ42K19XQ7",
        )
        # The callback's own effect. Without it the booking is still
        # PENDING_PAYMENT and `balance_due_for` is reading the in-flight
        # projection rather than what landed, which is not the state a client
        # ever sees this figure in.
        booking.status = AppointmentStatus.CONFIRMED
        booking.save(update_fields=["status"])

        assert paid_deposit_for(booking) == DEPOSIT
        assert balance_due_for(booking) == PRICE - DEPOSIT

    def test_a_failed_push_leaves_only_the_credit_paid(self, shop_setup, wednesday, early, held):
        """The coincidence broken. Credit was spent, cash never arrived.

        `paid_deposit_for` is the assertion that matters: a payment row that did
        not succeed is not money, and the naive `deposit_snapshot + redemptions`
        would report the full 875 here. The balance is checked against a settled
        booking for the same reason as above — while one is pending, the figure
        is deliberately a projection of the deposit still on its way."""
        booking = _book_with_credit(shop_setup, wednesday, early, held, 400)
        Payment.objects.create(
            appointment=booking,
            amount=booking.deposit_snapshot,
            phone=PHONE,
            state=PaymentState.FAILED,
            support_code="BK-TEST02",
        )
        booking.status = AppointmentStatus.CONFIRMED
        booking.save(update_fields=["status"])

        assert paid_deposit_for(booking) == 400
        assert balance_due_for(booking) == PRICE - 400
