"""The deposit rule as it lives on a Service, and the public-bookability rule
derived from it.

CLAUDE.md §5 and §12: the shop sets the rule, service creation pre-fills 25%,
and a service with no deposit is not publicly bookable — because without a
payment there is no phone verification, so an unverified number would hold a
slot for free.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError

from shops.models import DepositMode, Service

pytestmark = pytest.mark.django_db


def make_service(shop, **overrides):
    fields = {
        "shop": shop,
        "name": "Test service",
        "duration_minutes": 60,
        "price": 3500,
        "deposit_mode": DepositMode.PERCENT,
        "deposit_value": Decimal("25"),
    }
    return Service.objects.create(**{**fields, **overrides})


class TestThePreFill:
    def test_a_new_service_defaults_to_twenty_five_percent(self, shop_setup):
        """Charging nothing has to be a deliberate change, not the path of
        least resistance — so the field defaults rather than starting blank."""
        service = Service(shop=shop_setup.shop, name="X", duration_minutes=30, price=1000)

        assert service.deposit_mode == DepositMode.PERCENT
        assert service.deposit_value == Decimal("25")

    def test_the_pre_fill_produces_a_real_amount_on_save(self, shop_setup):
        service = make_service(shop_setup.shop, price=2000)

        assert service.deposit_amount == 500


class TestTheStoredAmount:
    def test_it_is_written_by_the_one_function(self, shop_setup):
        from shops.money import deposit_amount

        service = make_service(shop_setup.shop, price=1333)

        assert service.deposit_amount == deposit_amount(
            mode=service.deposit_mode, value=service.deposit_value, price=service.price
        )
        assert service.deposit_amount == 333

    def test_changing_the_price_recomputes_it(self, shop_setup):
        """The stored column is a cache of the function, so it must never be
        allowed to go stale behind a price change."""
        service = make_service(shop_setup.shop, price=2000)
        assert service.deposit_amount == 500

        service.price = 4000
        service.save()

        assert service.deposit_amount == 1000

    def test_a_partial_save_still_recomputes_it(self, shop_setup):
        """`save(update_fields=["price"])` must carry deposit_amount along, or
        the column silently disagrees with the price beside it."""
        service = make_service(shop_setup.shop, price=2000)

        service.price = 800
        service.save(update_fields=["price"])
        service.refresh_from_db()

        assert service.deposit_amount == 200

    def test_switching_to_no_deposit_zeroes_it(self, shop_setup):
        service = make_service(shop_setup.shop)
        assert service.deposit_amount > 0

        service.deposit_mode = DepositMode.NONE
        service.deposit_value = None
        service.save()

        assert service.deposit_amount == 0

    def test_it_is_not_settable_through_the_api_serializer(self):
        from shops.serializers import ServiceSerializer

        assert ServiceSerializer().fields["deposit_amount"].read_only


class TestValidation:
    def test_no_deposit_must_not_carry_a_value(self, shop_setup):
        service = Service(
            shop=shop_setup.shop,
            name="X",
            duration_minutes=30,
            price=1000,
            deposit_mode=DepositMode.NONE,
            deposit_value=Decimal("25"),
        )
        with pytest.raises(ValidationError):
            service.clean()

    def test_a_deposit_mode_requires_a_value(self, shop_setup):
        service = Service(
            shop=shop_setup.shop,
            name="X",
            duration_minutes=30,
            price=1000,
            deposit_mode=DepositMode.FLAT,
            deposit_value=None,
        )
        with pytest.raises(ValidationError):
            service.clean()

    def test_a_flat_deposit_must_be_whole_shillings(self, shop_setup):
        """There is no way to move 50 cents through an STK push."""
        service = Service(
            shop=shop_setup.shop,
            name="X",
            duration_minutes=30,
            price=1000,
            deposit_mode=DepositMode.FLAT,
            deposit_value=Decimal("500.50"),
        )
        with pytest.raises(ValidationError):
            service.clean()

    def test_a_flat_deposit_above_the_price_is_rejected(self, shop_setup):
        service = Service(
            shop=shop_setup.shop,
            name="X",
            duration_minutes=30,
            price=1000,
            deposit_mode=DepositMode.FLAT,
            deposit_value=Decimal("2000"),
        )
        with pytest.raises(ValidationError):
            service.clean()

    def test_a_percentage_above_a_hundred_is_rejected(self, shop_setup):
        service = Service(
            shop=shop_setup.shop,
            name="X",
            duration_minutes=30,
            price=1000,
            deposit_mode=DepositMode.PERCENT,
            deposit_value=Decimal("150"),
        )
        with pytest.raises(ValidationError):
            service.clean()

    def test_the_database_refuses_it_too(self, shop_setup):
        """Validation lives in `clean`, but the constraint is in Postgres, so a
        bad row cannot arrive through the admin, a shell or a data migration."""
        with pytest.raises(IntegrityError):
            Service.objects.create(
                shop=shop_setup.shop,
                name="X",
                duration_minutes=30,
                price=1000,
                deposit_mode=DepositMode.NONE,
                deposit_value=Decimal("25"),
            )


class TestPublicBookability:
    def test_a_deposit_free_service_is_not_publicly_bookable(self, shop_setup):
        """The locked decision from CLAUDE.md §12, at the model layer."""
        assert shop_setup.shave.deposit_mode == DepositMode.NONE
        assert shop_setup.shave.is_publicly_bookable is False

    def test_a_service_with_a_deposit_is(self, shop_setup):
        assert shop_setup.braids.is_publicly_bookable is True

    def test_deactivating_removes_bookability(self, shop_setup):
        shop_setup.braids.is_active = False
        shop_setup.braids.save()

        assert shop_setup.braids.is_publicly_bookable is False

    def test_unlisting_removes_bookability_without_touching_the_deposit(self, shop_setup):
        """Owner intent is necessary but not sufficient — a staff-only service
        keeps its deposit rule while being invisible to clients."""
        shop_setup.braids.is_publicly_listed = False
        shop_setup.braids.save()

        assert shop_setup.braids.is_publicly_bookable is False
        assert shop_setup.braids.deposit_amount == 875

    def test_it_is_derived_not_stored(self):
        """No column, so nothing to drift out of step with the deposit rule."""
        columns = {field.name for field in Service._meta.get_fields()}
        assert "is_publicly_bookable" not in columns
        assert isinstance(Service.is_publicly_bookable, property)

    @pytest.mark.parametrize("is_active", [True, False])
    @pytest.mark.parametrize("is_listed", [True, False])
    @pytest.mark.parametrize("mode", [DepositMode.NONE, DepositMode.FLAT, DepositMode.PERCENT])
    def test_the_python_property_and_the_sql_filter_always_agree(
        self, shop_setup, is_active, is_listed, mode
    ):
        """The rule is expressed twice — once as a property for a single row,
        once as a Q object for the public list. Two expressions of one rule is
        exactly how drift starts, so this walks the whole matrix."""
        service = make_service(
            shop_setup.shop,
            is_active=is_active,
            is_publicly_listed=is_listed,
            deposit_mode=mode,
            deposit_value=None if mode == DepositMode.NONE else Decimal("25"),
        )

        in_queryset = (
            Service.objects.for_org(shop_setup.organization)
            .publicly_bookable()
            .filter(pk=service.pk)
            .exists()
        )
        assert in_queryset == service.is_publicly_bookable
