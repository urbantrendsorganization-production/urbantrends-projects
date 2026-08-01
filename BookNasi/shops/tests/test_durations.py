"""Duration resolution — the function slice 3 imports.

CLAUDE.md §3: if the schedule cannot express that a senior stylist takes 30
minutes where a junior takes 50, the calendar lies and staff stop trusting it.
"""

import pytest

from shops.durations import ServiceNotOffered, resolve_duration
from shops.models import StaffService

pytestmark = pytest.mark.django_db


class TestResolutionOrder:
    def test_the_override_wins_when_present(self, shop_setup):
        link = StaffService.objects.for_org(shop_setup.organization).get(
            staff=shop_setup.wanjiku, service=shop_setup.braids
        )
        link.duration_override_minutes = 210
        link.save()

        assert resolve_duration(service=shop_setup.braids, staff_service=link) == 210

    def test_the_service_default_applies_when_there_is_no_override(self, shop_setup):
        link = StaffService.objects.for_org(shop_setup.organization).get(
            staff=shop_setup.grace, service=shop_setup.braids
        )

        assert link.duration_override_minutes is None
        assert resolve_duration(service=shop_setup.braids, staff_service=link) == 240

    def test_two_stylists_can_disagree_about_the_same_service(self, shop_setup):
        """The design's screen 2 draws exactly this: Wanjiku 3 hr 30, Grace
        4 hr 15. It is not decoration — it has to drive availability."""
        wanjiku_link = StaffService.objects.for_org(shop_setup.organization).get(
            staff=shop_setup.wanjiku, service=shop_setup.braids
        )
        wanjiku_link.duration_override_minutes = 210
        wanjiku_link.save()
        grace_link = StaffService.objects.for_org(shop_setup.organization).get(
            staff=shop_setup.grace, service=shop_setup.braids
        )
        grace_link.duration_override_minutes = 255
        grace_link.save()

        assert shop_setup.wanjiku.duration_for(shop_setup.braids) == 210
        assert shop_setup.grace.duration_for(shop_setup.braids) == 255


class TestNotOffered:
    def test_no_link_at_all_raises(self, shop_setup):
        """Not a duration of zero, and not a silent fall back to the service
        default. The engine must not invent a slot for a stylist who cannot do
        the job."""
        with pytest.raises(ServiceNotOffered):
            resolve_duration(service=shop_setup.braids, staff_service=None)

    def test_a_link_with_is_offered_false_raises(self, shop_setup):
        link = StaffService.objects.for_org(shop_setup.organization).get(
            staff=shop_setup.grace, service=shop_setup.braids
        )
        link.is_offered = False
        link.save()

        with pytest.raises(ServiceNotOffered):
            resolve_duration(service=shop_setup.braids, staff_service=link)

    def test_the_model_helper_raises_too(self, shop_setup):
        """`Staff.duration_for` delegates to the same function, so it must fail
        the same way rather than returning None."""
        StaffService.objects.for_org(shop_setup.organization).filter(
            staff=shop_setup.grace, service=shop_setup.braids
        ).delete()

        with pytest.raises(ServiceNotOffered):
            shop_setup.grace.duration_for(shop_setup.braids)


class TestDelegation:
    def test_the_model_property_and_the_function_agree(self, shop_setup):
        """`StaffService.effective_duration_minutes` must delegate, not
        reimplement. A second implementation is how the API and the engine end
        up reporting different durations for the same booking."""
        link = StaffService.objects.for_org(shop_setup.organization).get(
            staff=shop_setup.wanjiku, service=shop_setup.braids
        )
        link.duration_override_minutes = 195
        link.save()

        assert link.effective_duration_minutes == resolve_duration(
            service=shop_setup.braids, staff_service=link
        )

    def test_a_zero_override_is_impossible_so_falsiness_cannot_bite(self, shop_setup):
        """`override or default` would treat 0 as absent. The model rejects a
        zero override, and the function checks `is not None` regardless."""
        from django.core.exceptions import ValidationError

        link = StaffService.objects.for_org(shop_setup.organization).get(
            staff=shop_setup.wanjiku, service=shop_setup.braids
        )
        link.duration_override_minutes = 0
        with pytest.raises(ValidationError):
            link.full_clean()
