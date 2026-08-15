"""Credit spent on a booking comes back when §12 says the deposit is refundable.

Slice 11's walk cancelled a credit-paid booking more than 24 hours out, was told
"the shop will refund your KES 300", and nothing anywhere recorded it: the
"Refund owed to the client" queue stayed empty and the credit stayed spent.
`lifecycle.cancel` records a refund by stamping `Payment.refund_due_at`, and a
booking whose deposit came from credit has no `Payment` row for that filter to
match, so the `.update()` touched nothing at all. The money left.

Three decisions are protected here rather than merely implemented, which is why
this file is marked load-bearing:

1. **Money returns in the form it arrived.** Credit comes back as credit, cash
   is still stamped for the exception queue, and a mixed deposit does both. Cash
   for the credit half would turn credit into a withdrawal — a credit exists
   because a *late* cancellation keeps the money at the shop, so a client who
   could book and cancel early would launder it out at will.

2. **A restored credit keeps the original expiry.** A fresh
   `deposit_credit_days` window would make spend-and-cancel an unbounded
   extension: sixty more days, every time, forever. `test_the_expiry_is_not_
   extended_by_a_round_trip` is the one that matters here, and it is the reason
   the restore is a new row copying a date rather than a new issuance.

3. **The same rule on the late-cancellation branch**, which is where the
   loophole was widest. §12 turns a late-cancelled deposit into credit on a
   fresh window — right for cash, and for a deposit paid *with* credit it meant
   the same money came back renewed, repeatable without limit, two lines from
   where (2) closed it. `TestALateCancellationCannotRenewAWindow` splits the
   deposit: the credit-funded half restored on its own expiry, the cash half
   issued fresh exactly as §12 says.

Each of the three has a test that fails against the behaviour it replaced;
`test_no_second_credit_is_minted_for_money_that_was_already_credit` does not,
and is kept as a statement of shape rather than as a guard.
"""

from datetime import timedelta

import pytest

from payments import credit as credit_module
from payments.credit import Credit, CreditSource
from payments.models import Payment
from payments.states import PaymentState
from scheduling import lifecycle
from scheduling.holds import confirm_credit_covered, create_hold
from scheduling.tests.conftest import eat

pytestmark = [pytest.mark.django_db, pytest.mark.loadbearing]

PHONE = "+254712345678"
DEPOSIT = 875


@pytest.fixture
def early(wednesday):
    """Well before the shop opens, so lead time never interferes. The same
    fixture `scheduling/tests` has; redefined because conftests do not reach
    sideways across apps."""
    return eat(wednesday, 5, 0)


@pytest.fixture
def friday(wednesday):
    """Two days out, which is what puts a cancellation *outside* the shop's
    24-hour refund window and makes §12's outcome REFUND rather than CREDIT.

    Every booking here that is meant to be refundable sits on this day. Putting
    them on `wednesday` alongside `early` is only six hours of notice, so the
    first draft of this file tested the credit branch throughout while claiming
    to test the refund one."""
    return wednesday + timedelta(days=2)


@pytest.fixture
def source_booking(shop_setup, wednesday, early):
    return create_hold(
        shop=shop_setup.shop,
        service=shop_setup.braids,
        staff=shop_setup.wanjiku,
        starts_at=eat(wednesday, 10, 0),
        phone=PHONE,
        now=early,
    )


def _credit_paid_booking(shop_setup, friday, early, source_booking, credit_kes=DEPOSIT):
    """A booking whose deposit shop credit covered, confirmed as the view does."""
    credit_module.issue(appointment=source_booking, payment=None, amount_kes=credit_kes, now=early)
    booking = create_hold(
        shop=shop_setup.shop,
        service=shop_setup.braids,
        staff=shop_setup.grace,
        starts_at=eat(friday, 11, 0),
        phone=PHONE,
        now=early,
    )
    if booking.deposit_snapshot < 1:
        confirm_credit_covered(booking, now=early)
        booking.refresh_from_db()
    return booking


class TestTheMoneyComesBack:
    def test_a_refundable_cancellation_returns_the_credit(
        self, shop_setup, friday, early, source_booking
    ):
        """The walk's defect, directly. Cancelled well outside the window."""
        booking = _credit_paid_booking(shop_setup, friday, early, source_booking)

        outcome, amount, _ = lifecycle.cancel(booking, now=early)

        assert outcome == lifecycle.Outcome.REFUND
        assert amount == DEPOSIT
        restored = Credit.objects.unscoped().filter(source=CreditSource.BOOKING_REFUNDED)
        assert restored.count() == 1
        assert restored.first().remaining_kes == DEPOSIT

    def test_the_client_can_spend_it_again(self, shop_setup, friday, early, source_booking):
        """The assertion that would have caught it without knowing the mechanism:
        the client's spendable balance is what it was before they booked."""
        booking = _credit_paid_booking(shop_setup, friday, early, source_booking)
        client = booking.client
        assert credit_module.balance_for(client, shop_setup.shop, now=early) == 0

        lifecycle.cancel(booking, now=early)

        assert credit_module.balance_for(client, shop_setup.shop, now=early) == DEPOSIT

    def test_it_is_not_also_queued_as_a_cash_refund(
        self, shop_setup, friday, early, source_booking
    ):
        """Both halves would be double-paying. There is no `Payment` on this
        booking to stamp, and none is invented."""
        booking = _credit_paid_booking(shop_setup, friday, early, source_booking)

        lifecycle.cancel(booking, now=early)

        assert (
            not Payment.objects.unscoped()
            .filter(appointment=booking, refund_due_at__isnull=False)
            .exists()
        )


class TestTheExpiryIsNotAWindowReset:
    def test_the_expiry_is_not_extended_by_a_round_trip(
        self, shop_setup, friday, early, source_booking
    ):
        """The loophole this decision closes.

        Spend a credit, cancel refundably, get it back — and if the returned
        credit carried a fresh `deposit_credit_days`, that cycle extends it for
        another sixty days and can be repeated without limit. The restored row
        carries the *source* credit's date, to the second."""
        booking = _credit_paid_booking(shop_setup, friday, early, source_booking)
        original = Credit.objects.unscoped().get(source=CreditSource.LATE_CANCELLATION)

        lifecycle.cancel(booking, now=early)

        restored = Credit.objects.unscoped().get(source=CreditSource.BOOKING_REFUNDED)
        assert restored.expires_at == original.expires_at

    def test_a_lapsed_credit_comes_back_lapsed(self, shop_setup, friday, early, source_booking):
        """The honest consequence of the rule above, asserted so nobody
        'fixes' it into an extension by accident. Money whose window closed
        while it was tied up in a booking does not reopen."""
        booking = _credit_paid_booking(shop_setup, friday, early, source_booking)
        original = Credit.objects.unscoped().get(source=CreditSource.LATE_CANCELLATION)

        lifecycle.cancel(booking, now=early)

        restored = Credit.objects.unscoped().get(source=CreditSource.BOOKING_REFUNDED)
        after_expiry = original.expires_at + timedelta(days=1)
        assert restored.expires_at < after_expiry
        assert (
            not Credit.objects.unscoped()
            .filter(pk=restored.pk, expires_at__gt=after_expiry)
            .exists()
        )


class TestAMixedDeposit:
    def test_cash_is_queued_and_credit_is_returned(self, shop_setup, friday, early, source_booking):
        """Each half goes back the way it came, once each."""
        booking = _credit_paid_booking(shop_setup, friday, early, source_booking, credit_kes=400)
        Payment.objects.create(
            appointment=booking,
            amount=booking.deposit_snapshot,
            phone=PHONE,
            state=PaymentState.SUCCEEDED,
            support_code="BK-MIX001",
            mpesa_receipt="SJ42K19XQ7",
        )

        lifecycle.cancel(booking, now=early)

        cash = Payment.objects.unscoped().get(appointment=booking)
        assert cash.refund_due_at is not None, "the M-Pesa half owes the client cash"
        restored = Credit.objects.unscoped().get(source=CreditSource.BOOKING_REFUNDED)
        assert restored.amount_kes == 400, "and only the credit half comes back as credit"


class TestTheMessageFollowsTheMoney:
    def test_it_does_not_promise_a_transfer_that_is_not_coming(
        self, shop_setup, friday, early, source_booking
    ):
        """ "The shop will refund you" for money that came back as credit leaves
        the client waiting for an M-Pesa transfer nobody is going to send."""
        from notifications.models import Message
        from notifications.templates import Template, render

        booking = _credit_paid_booking(shop_setup, friday, early, source_booking)

        lifecycle.cancel(booking, now=early)

        message = Message.objects.unscoped().get(
            appointment=booking, template=Template.CANCELLED_REFUND
        )
        body = render(message.template, message.variables)
        assert "back as credit" in body
        assert "refunded by the shop" not in body
        assert f"{DEPOSIT:,}" in body

    def test_a_cash_refund_still_reads_the_way_it_always_did(self, shop_setup, friday, early):
        """No credit involved, no change. The wording that shipped in slice 7 is
        still what an ordinary M-Pesa deposit gets back."""
        from notifications.models import Message
        from notifications.templates import Template, render

        booking = create_hold(
            shop=shop_setup.shop,
            service=shop_setup.braids,
            staff=shop_setup.wanjiku,
            starts_at=eat(friday, 9, 0),
            phone=PHONE,
            now=early,
        )
        Payment.objects.create(
            appointment=booking,
            amount=booking.deposit_snapshot,
            phone=PHONE,
            state=PaymentState.SUCCEEDED,
            support_code="BK-CASH01",
            mpesa_receipt="TQ88M04ZR2",
        )

        lifecycle.cancel(booking, now=early)

        message = Message.objects.unscoped().get(
            appointment=booking, template=Template.CANCELLED_REFUND
        )
        body = render(message.template, message.variables)
        assert "refunded by the shop" in body
        assert "back as credit" not in body
        # The figure, not "KES 0". `variables_for` has no payment and no credit
        # to read on this branch, so `paid` fell through its `setdefault` and
        # every refund SMS ever sent named zero shillings. Nothing asserted the
        # amount, only the sentence, so the suite stayed green over it.
        assert f"KES {DEPOSIT:,}" in body

    def test_a_mixed_refund_names_both_halves(self, shop_setup, friday, early, source_booking):
        """Cash and credit in one message, because a client chasing only the
        half they were told about is the support call either omission causes."""
        from notifications.models import Message
        from notifications.templates import Template, render

        booking = _credit_paid_booking(shop_setup, friday, early, source_booking, credit_kes=400)
        Payment.objects.create(
            appointment=booking,
            amount=booking.deposit_snapshot,
            phone=PHONE,
            state=PaymentState.SUCCEEDED,
            support_code="BK-MIX002",
            mpesa_receipt="RK55N21WQ8",
        )

        lifecycle.cancel(booking, now=early)

        message = Message.objects.unscoped().get(
            appointment=booking, template=Template.CANCELLED_REFUND
        )
        body = render(message.template, message.variables)
        assert f"KES {DEPOSIT - 400:,} will be refunded by the shop" in body
        assert "KES 400 is back as credit" in body


class TestALateCancellationCannotRenewAWindow:
    """The mirror image, and the reason this rule is not only about refunds.

    §12 turns a late-cancelled deposit into credit on a fresh
    `deposit_credit_days` window. That is right for a deposit paid in cash and
    wrong for one paid with credit: spend a credit, cancel late, and the same
    money comes back with another sixty days on it — repeatable without limit,
    two lines away from the refund branch where the same loophole was closed.
    So the credit-funded half is restored on its own expiry and only the cash
    half is issued fresh.
    """

    def test_a_wholly_credit_paid_deposit_keeps_its_original_expiry(
        self, shop_setup, friday, early, source_booking
    ):
        booking = _credit_paid_booking(shop_setup, friday, early, source_booking)
        original = Credit.objects.unscoped().get(source=CreditSource.LATE_CANCELLATION)
        inside = booking.starts_at - timedelta(hours=1)

        outcome, amount, _ = lifecycle.cancel(booking, now=inside)

        assert outcome == lifecycle.Outcome.CREDIT
        assert amount == DEPOSIT
        back = Credit.objects.unscoped().get(source=CreditSource.BOOKING_REFUNDED)
        assert back.amount_kes == DEPOSIT
        assert back.expires_at == original.expires_at, "a spent credit cannot renew itself"

    def test_no_second_credit_is_minted_for_money_that_was_already_credit(
        self, shop_setup, friday, early, source_booking
    ):
        """The bug this replaces issued the *whole* deposit fresh. Doing both
        would hand the client their deposit twice."""
        booking = _credit_paid_booking(shop_setup, friday, early, source_booking)
        inside = booking.starts_at - timedelta(hours=1)

        lifecycle.cancel(booking, now=inside)

        assert Credit.objects.unscoped().filter(client=booking.client).count() == 2, (
            "the original, now spent, and the one restored on its expiry"
        )
        assert credit_module.balance_for(booking.client, shop_setup.shop, now=inside) == DEPOSIT

    def test_a_cash_deposit_still_gets_a_fresh_window(self, shop_setup, friday, early):
        """§12 unchanged for the ordinary case: cash late-cancelled becomes
        credit valid `deposit_credit_days` from now."""
        booking = create_hold(
            shop=shop_setup.shop,
            service=shop_setup.braids,
            staff=shop_setup.wanjiku,
            starts_at=eat(friday, 9, 0),
            phone=PHONE,
            now=early,
        )
        Payment.objects.create(
            appointment=booking,
            amount=booking.deposit_snapshot,
            phone=PHONE,
            state=PaymentState.SUCCEEDED,
            support_code="BK-LATE01",
            mpesa_receipt="TQ88M04ZR2",
        )
        inside = booking.starts_at - timedelta(hours=1)

        _, _, issued = lifecycle.cancel(booking, now=inside)

        assert issued is not None
        assert issued.source == CreditSource.LATE_CANCELLATION
        expected = inside + timedelta(days=shop_setup.shop.deposit_credit_days)
        assert abs((issued.expires_at - expected).total_seconds()) < 5

    def test_a_mixed_deposit_splits_across_two_windows(
        self, shop_setup, friday, early, source_booking
    ):
        """Each half on the window it is entitled to, and no more."""
        booking = _credit_paid_booking(shop_setup, friday, early, source_booking, credit_kes=400)
        original = Credit.objects.unscoped().get(source=CreditSource.LATE_CANCELLATION)
        Payment.objects.create(
            appointment=booking,
            amount=booking.deposit_snapshot,
            phone=PHONE,
            state=PaymentState.SUCCEEDED,
            support_code="BK-MIX003",
            mpesa_receipt="RK55N21WQ8",
        )
        inside = booking.starts_at - timedelta(hours=1)

        _, amount, issued = lifecycle.cancel(booking, now=inside)

        assert amount == DEPOSIT
        back = Credit.objects.unscoped().get(source=CreditSource.BOOKING_REFUNDED)
        assert back.amount_kes == 400
        assert back.expires_at == original.expires_at
        assert issued.amount_kes == DEPOSIT - 400
        assert issued.expires_at > original.expires_at, "the cash half earns a new window"
        assert credit_module.balance_for(booking.client, shop_setup.shop, now=inside) == DEPOSIT


def test_the_restored_credit_keeps_the_payment_chain(shop_setup, friday, early, source_booking):
    """§5's carve-out treats a credit-covered booking as verified because the
    credit descends from a real M-Pesa success. A restored credit that dropped
    `source_payment` would quietly stop satisfying that."""
    payment = Payment.objects.create(
        appointment=source_booking,
        amount=DEPOSIT,
        phone=PHONE,
        state=PaymentState.SUCCEEDED,
        support_code="BK-CHAIN1",
        mpesa_receipt="SJ42K19XQ7",
    )
    credit_module.issue(appointment=source_booking, payment=payment, amount_kes=DEPOSIT, now=early)
    booking = create_hold(
        shop=shop_setup.shop,
        service=shop_setup.braids,
        staff=shop_setup.grace,
        starts_at=eat(friday, 11, 0),
        phone=PHONE,
        now=early,
    )
    confirm_credit_covered(booking, now=early)

    lifecycle.cancel(booking, now=early)

    restored = Credit.objects.unscoped().get(source=CreditSource.BOOKING_REFUNDED)
    assert restored.source_payment_id == payment.pk
