"""The refund policy, settled 14 August 2026. CLAUDE.md §12.

Four outcomes:

    cancel earlier than `refund_window_hours` -> refunded
    cancel later than it                      -> credit, `deposit_credit_days`
    no-show                                   -> forfeited
    the shop cancels                          -> refunded, regardless

Only the first two are fields. The other two are not the shop's to vary — a
forfeit the client can avoid by turning up, and a refund they cannot lose to a
cancellation they did not make — so there is nothing here to test but their
absence, which is what `test_the_policy_has_exactly_two_knobs` is for.

§5 requires the client to read the terms *before* they pay. The wording lives in
`packages/booking-core/src/money.refundSentence` and is tested there; what these
tests hold is that the numbers behind it reach the client at all, on both
screens that state them — the confirm screen, and the booking page the
confirmation SMS links to.
"""

import pytest

from shops.models import Shop

pytestmark = pytest.mark.django_db


class TestTheDefaults:
    def test_a_new_shop_gets_the_policy_without_being_asked(self, shop_setup):
        """Defaults, not a setup step. A shop that has to opt in to a refund
        policy is a shop with no refund policy on the day it opens."""
        shop = Shop.objects.unscoped().get(pk=shop_setup.shop.pk)

        assert shop.refund_window_hours == 24
        assert shop.deposit_credit_days == 60

    def test_the_credit_window_is_bounded(self, shop_setup):
        """A CHECK constraint, not a validator alone. `full_clean` is not called
        on every write and the column is what the client's sentence is rendered
        from — "credit for 0 days" is a forfeit wearing a different word."""
        from django.db import IntegrityError, transaction

        shop = shop_setup.shop
        for bad in (0, 366):
            with pytest.raises(IntegrityError), transaction.atomic():
                Shop.objects.unscoped().filter(pk=shop.pk).update(deposit_credit_days=bad)

    def test_the_policy_has_exactly_two_knobs(self):
        """The no-show forfeit and the shop-cancels refund are deliberately not
        configurable. A shop that could keep a deposit against its own
        cancellation is a term no client would accept if they read it — and §5
        says they read it."""
        fields = {f.name for f in Shop._meta.get_fields()}

        assert "refund_window_hours" in fields
        assert "deposit_credit_days" in fields
        for never in ("no_show_forfeit", "shop_cancel_refund", "forfeit_on_no_show"):
            assert never not in fields


class TestTheClientCanReadThem:
    """Both numbers, on both surfaces that state the terms."""

    def test_the_shop_endpoint_carries_both_numbers(self, api_client, shop_setup):
        """The confirm screen renders its sentence from these, before payment."""
        from django.urls import reverse

        body = api_client.get(reverse("public_api:shop-detail", args=[shop_setup.shop.slug])).json()

        assert body["refund_window_hours"] == 24
        assert body["deposit_credit_days"] == 60

    def test_the_hold_endpoint_carries_them_too(self, api_client, shop_setup):
        """The booking page the confirmation SMS links to has no shop object —
        it is reached by appointment id from an SMS, not by slug from the
        booking flow. Without these on the hold it could not state the terms,
        and the terms would be readable only before payment and never after,
        which is exactly backwards for the screen a client opens when they are
        deciding whether to cancel.
        """
        from datetime import timedelta

        from django.urls import reverse

        from scheduling.holds import create_hold
        from scheduling.tests.conftest import WEDNESDAY, eat

        when = eat(WEDNESDAY, 10)
        hold = create_hold(
            shop=shop_setup.shop,
            service=shop_setup.braids,
            staff=shop_setup.wanjiku,
            starts_at=when,
            phone="0712345678",
            now=when - timedelta(hours=2),
        )

        body = api_client.get(reverse("public_api:hold-detail", args=[hold.pk])).json()

        assert body["refund_window_hours"] == 24
        assert body["deposit_credit_days"] == 60
        assert body["shop_name"] == shop_setup.shop.name

    def test_a_shop_with_its_own_numbers_is_reported_with_them(self, api_client, shop_setup):
        """Not hardcoded anywhere on the way out."""
        from django.urls import reverse

        Shop.objects.unscoped().filter(pk=shop_setup.shop.pk).update(
            refund_window_hours=48, deposit_credit_days=90
        )

        body = api_client.get(reverse("public_api:shop-detail", args=[shop_setup.shop.slug])).json()

        assert body["refund_window_hours"] == 48
        assert body["deposit_credit_days"] == 90
