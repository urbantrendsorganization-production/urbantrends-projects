"""`Service.deposit_amount` must never disagree with `shops.money`.

The 12-combination bookability test cannot catch this class of bug, because it
goes through `save()` — which is exactly the method the three bulk paths skip.
These tests deliberately take the bypasses.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.utils import IntegrityError

from shops.integrity import StaleDepositError
from shops.models import DepositMode, Service, Shop
from shops.money import deposit_amount

pytestmark = pytest.mark.django_db


def stored(service):
    return Service.all_objects.get(pk=service.pk).deposit_amount


def expected(service):
    return deposit_amount(
        mode=service.deposit_mode,
        value=service.deposit_value,
        price=service.price,
        minimum=service.shop.min_deposit_amount,
    )


class TestUpdateRefuses:
    """`.update()` cannot recompute — a single SQL statement cannot express
    half-up rounding, the shop floor and the price clamp without restating the
    money arithmetic in SQL. So it refuses, loudly, and names the alternative.
    """

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"price": 6000},
            {"deposit_mode": DepositMode.FLAT, "deposit_value": Decimal("1000")},
            {"deposit_value": Decimal("50")},
            {"deposit_amount": 1},
        ],
        ids=["price", "mode+value", "value", "the derived column itself"],
    )
    def test_touching_a_deposit_input_raises(self, shop_setup, kwargs):
        qs = Service.objects.for_org(shop_setup.organization).filter(pk=shop_setup.braids.pk)

        with pytest.raises(StaleDepositError):
            qs.update(**kwargs)

    def test_the_error_says_what_to_do_instead(self, shop_setup):
        qs = Service.objects.for_org(shop_setup.organization)

        with pytest.raises(StaleDepositError, match="save"):
            qs.update(price=6000)

    def test_an_unrelated_update_still_works(self, shop_setup):
        """Deactivation is the common bulk write and must stay cheap. The guard
        is aimed at the deposit inputs, not at `.update()` in general."""
        qs = Service.objects.for_org(shop_setup.organization).filter(pk=shop_setup.braids.pk)

        assert qs.update(is_active=False) == 1
        assert Service.all_objects.get(pk=shop_setup.braids.pk).is_active is False

    def test_the_unguarded_manager_is_covered_too(self, shop_setup):
        """`all_objects` exists for Django's internals and skips the *tenancy*
        guard by design. It must not also skip this one, or the bypass is simply
        one attribute away."""
        with pytest.raises(StaleDepositError):
            Service.all_objects.filter(pk=shop_setup.braids.pk).update(price=6000)

    def test_the_row_is_untouched_after_a_refusal(self, shop_setup):
        with pytest.raises(StaleDepositError):
            Service.objects.for_org(shop_setup.organization).update(price=6000)

        fresh = Service.all_objects.get(pk=shop_setup.braids.pk)
        assert fresh.price == 3500
        assert fresh.deposit_amount == 875


class TestBulkUpdateRecomputes:
    """The rows are in memory here, so there is nothing to refuse — it behaves
    exactly like `save(update_fields=[...])`, which also appends the derived
    column."""

    def test_a_price_rise_carries_the_deposit_with_it(self, shop_setup):
        braids = Service.all_objects.get(pk=shop_setup.braids.pk)
        braids.price = 6000

        Service.all_objects.bulk_update([braids], ["price"])

        assert stored(braids) == 1500  # 25% of 6,000
        assert stored(braids) == expected(braids)

    def test_a_mode_change_carries_the_deposit_with_it(self, shop_setup):
        braids = Service.all_objects.get(pk=shop_setup.braids.pk)
        braids.deposit_mode = DepositMode.FLAT
        braids.deposit_value = Decimal("1200")

        Service.all_objects.bulk_update([braids], ["deposit_mode", "deposit_value"])

        assert stored(braids) == 1200

    def test_the_caller_does_not_have_to_know_to_list_the_derived_column(self, shop_setup):
        """The point of appending it rather than requiring it: a caller who
        lists only `price` gets a correct row, not a half-applied one."""
        braids = Service.all_objects.get(pk=shop_setup.braids.pk)
        braids.price = 4000

        Service.all_objects.bulk_update([braids], ["price"])

        assert stored(braids) == 1000

    def test_writing_the_derived_column_by_hand_is_still_refused(self, shop_setup):
        braids = Service.all_objects.get(pk=shop_setup.braids.pk)
        braids.deposit_amount = 1

        with pytest.raises(StaleDepositError):
            Service.all_objects.bulk_update([braids], ["deposit_amount"])

    def test_an_unrelated_bulk_update_does_not_touch_the_deposit(self, shop_setup):
        braids = Service.all_objects.get(pk=shop_setup.braids.pk)
        braids.name = "Knotless braids, small, waist length"

        Service.all_objects.bulk_update([braids], ["name"])

        assert stored(braids) == 875

    def test_the_shop_floor_is_applied_on_this_path_too(self, shop_setup):
        shop_setup.shop.min_deposit_amount = 400
        shop_setup.shop.save(update_fields=["min_deposit_amount"])

        braids = Service.all_objects.select_related("shop").get(pk=shop_setup.braids.pk)
        braids.price = 1000  # 25% is 250, under the raised floor

        Service.all_objects.bulk_update([braids], ["price"])

        assert stored(braids) == 400


class TestBulkCreateComputes:
    def test_a_bulk_created_service_is_not_left_at_zero(self, shop_setup):
        """The nastiest of the three. `deposit_amount` defaults to 0, and 0 is
        the value that means 'not publicly bookable' — so a bulk import would
        silently produce a shop whose whole menu is invisible to clients."""
        created = Service.all_objects.bulk_create(
            [
                Service(
                    shop=shop_setup.shop,
                    organization=shop_setup.organization,
                    name="Cornrows",
                    duration_minutes=90,
                    price=1200,
                    deposit_mode=DepositMode.PERCENT,
                    deposit_value=Decimal("25"),
                )
            ]
        )

        assert stored(created[0]) == 300
        assert Service.all_objects.get(pk=created[0].pk).is_publicly_bookable is True


class TestTheDatabaseBackstop:
    """A check constraint catches the part SQL can see unaided. It is a second
    net of a different kind, not a duplicate of the mixin."""

    def test_a_deposit_above_the_price_is_refused(self, shop_setup):
        """Raw SQL, deliberately: this is the one path the mixin cannot see, and
        it is what a migration or a psql session looks like."""
        with pytest.raises(IntegrityError):
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE services SET price = %s WHERE id = %s", [100, str(shop_setup.braids.pk)]
                )

    def test_a_deposit_on_a_deposit_free_service_is_refused(self, shop_setup):
        """The constraint that matters most: a non-zero deposit on a `none`
        service would make it publicly bookable, which CLAUDE.md §5 forbids."""
        with pytest.raises(IntegrityError):
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE services SET deposit_amount = %s WHERE id = %s",
                    [500, str(shop_setup.shave.pk)],
                )

    def test_a_deposit_free_service_stores_zero(self, shop_setup):
        assert stored(shop_setup.shave) == 0


class TestTheFlatDepositFloorIsValidatedNotSilentlyRaised:
    """Percentages and flat amounts are treated differently on purpose.

    An owner who typed a *rate* expects the floor to apply. An owner who typed
    an *amount* would be looking at a number they did not type, so that case is
    rejected at validation instead.
    """

    def test_a_flat_deposit_under_the_shop_floor_is_rejected(self, shop_setup):
        service = Service(
            shop=shop_setup.shop,
            name="Quick line-up",
            duration_minutes=15,
            price=300,
            deposit_mode=DepositMode.FLAT,
            deposit_value=Decimal("20"),
        )

        with pytest.raises(ValidationError) as excinfo:
            service.clean()

        assert "minimum deposit" in str(excinfo.value)

    def test_a_flat_deposit_at_the_floor_is_fine(self, shop_setup):
        service = Service(
            shop=shop_setup.shop,
            name="Quick line-up",
            duration_minutes=15,
            price=300,
            deposit_mode=DepositMode.FLAT,
            deposit_value=Decimal("50"),
        )

        service.clean()  # must not raise

    def test_a_service_priced_below_the_floor_may_prepay_in_full(self, shop_setup):
        """A KES 30 item cannot carry a KES 50 deposit. The whole price is the
        only sane answer, and validation must not block it."""
        service = Service(
            shop=shop_setup.shop,
            name="Eyebrow thread",
            duration_minutes=10,
            price=30,
            deposit_mode=DepositMode.FLAT,
            deposit_value=Decimal("30"),
        )

        service.clean()
        service.save()

        assert stored(service) == 30

    def test_a_percentage_under_the_floor_is_raised_rather_than_rejected(self, shop_setup):
        service = Service.objects.create(
            shop=shop_setup.shop,
            name="Wash and go",
            duration_minutes=30,
            price=400,
            deposit_mode=DepositMode.PERCENT,
            deposit_value=Decimal("5"),  # 20 shillings, under the 50 floor
        )

        assert stored(service) == 50


class TestTheShopFloorField:
    def test_it_defaults_to_fifty(self, org_a):
        shop = Shop.objects.create(organization=org_a.organization, name="New", slug="new-shop")

        assert shop.min_deposit_amount == 50

    def test_zero_is_refused_by_the_database(self, org_a):
        """A floor of zero is a floor of one shilling by another name, and the
        whole point of this field is that a token deposit is not a deposit."""
        with pytest.raises(IntegrityError):
            Shop.objects.create(
                organization=org_a.organization,
                name="No floor",
                slug="no-floor",
                min_deposit_amount=0,
            )
