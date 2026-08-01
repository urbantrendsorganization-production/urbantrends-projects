"""Read-only availability. Two audiences, one engine.

The public route answers "when can I book this?"; the org-scoped route answers
"what does my day look like?". They differ in exactly two things — who is
allowed to ask, and which `Policy` applies — and share the derivation, the
cache and the loader. Any divergence beyond those two would mean a client and a
stylist looking at different calendars.

Neither route writes. Slice 3 ships no booking endpoint on purpose;
`booking.create_appointment` exists and is tested, and slices 4 and 5 expose it.
"""

from datetime import date

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.tenancy import OrgScopedMixin
from public_api.views import PublicViewMixin
from scheduling.availability import Policy, derive_slots
from scheduling.cache import facts_for_shop_day
from scheduling.loading import staff_for_service
from scheduling.serializers import SlotSerializer, StaffSlotsSerializer
from shops.durations import ServiceNotOffered, resolve_duration
from shops.models import Service, Staff


def parse_date(raw):
    """`?date=YYYY-MM-DD`. Required — there is no implicit "today".

    Defaulting would make the response depend on the server's idea of now, and
    a client on a slow connection would silently get a different day than the
    one whose chip they tapped.
    """
    if not raw:
        raise ValueError("A date is required, as ?date=YYYY-MM-DD.")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("Dates look like 2026-08-14.") from exc


class AvailabilityForServiceMixin:
    """Slots for one service across a set of staff, on one EAT date."""

    def slots_by_staff(self, service, day, *, policy, only_staff=None):
        pairs = staff_for_service(service)
        if only_staff is not None:
            pairs = [(row, link) for row, link in pairs if row.id == only_staff.id]
        if not pairs:
            return []

        facts = facts_for_shop_day(service.shop, day, staff=[row for row, _ in pairs])
        out = []
        for staff_row, link in pairs:
            try:
                duration = resolve_duration(service=service, staff_service=link)
            except ServiceNotOffered:
                continue
            out.append(
                {
                    "staff_id": staff_row.id,
                    "display_name": staff_row.display_name,
                    "slots": derive_slots(
                        facts[staff_row.id],
                        duration_minutes=duration,
                        policy=policy,
                        now=self.now(),
                    ),
                }
            )
        return out

    def now(self):
        from django.utils import timezone

        return timezone.now()


class PublicAvailabilityView(PublicViewMixin, AvailabilityForServiceMixin, APIView):
    """`GET /api/public/v1/shops/<slug>/services/<id>/availability/?date=&staff=`

    A deposit-free service 404s here exactly as it is absent from the public
    service list — CLAUDE.md §5, enforced at the API rather than the UI. Without
    a payment there is no phone verification, so there is nothing to offer.
    """

    def get(self, request, slug, service_id):
        shop = self.get_shop()
        service = get_object_or_404(
            Service.objects.for_org(shop.organization).filter(shop=shop).publicly_bookable(),
            pk=service_id,
        )
        try:
            day = parse_date(request.query_params.get("date"))
        except ValueError as exc:
            return Response({"date": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)

        only_staff = None
        if request.query_params.get("staff"):
            only_staff = get_object_or_404(
                Staff.objects.for_org(shop.organization).filter(
                    shop=shop, is_active=True, is_bookable=True
                ),
                pk=request.query_params["staff"],
            )

        # The public policy: minimum lead time and booking horizon both apply.
        by_staff = self.slots_by_staff(
            service, day, policy=Policy.for_public(shop), only_staff=only_staff
        )
        return Response(
            {
                "date": day.isoformat(),
                "service_id": str(service.id),
                # "Anyone available" is the earliest free start across everyone
                # who does the job — CLAUDE.md §12, an earliest-available-slot
                # rule and explicitly not an assignment algorithm. The staff
                # member who owns each start is named so the confirm step has
                # something to book against.
                "any_staff": SlotSerializer(_earliest_per_start(by_staff), many=True).data,
                "by_staff": StaffSlotsSerializer(by_staff, many=True).data,
            }
        )


class StaffAvailabilityView(OrgScopedMixin, AvailabilityForServiceMixin, APIView):
    """`GET /api/v1/orgs/<org>/shops/<shop>/staff/<staff>/availability/?date=&service=`

    The staff-side view of the same engine, under `Policy.for_staff()`: no lead
    time and no horizon. A walk-in starts now, and refusing it because
    `now + 30 minutes` has not arrived would make the product unusable for the
    majority of Kenyan salon trade — CLAUDE.md §4.
    """

    def get(self, request, org_id, shop_id, staff_id):
        staff_row = get_object_or_404(
            Staff.objects.for_org(self.organization).filter(shop_id=shop_id), pk=staff_id
        )
        service = get_object_or_404(
            Service.objects.for_org(self.organization).filter(shop_id=shop_id),
            pk=request.query_params.get("service"),
        )
        try:
            day = parse_date(request.query_params.get("date"))
        except ValueError as exc:
            return Response({"date": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)

        by_staff = self.slots_by_staff(
            service, day, policy=Policy.for_staff(), only_staff=staff_row
        )
        return Response(
            {
                "date": day.isoformat(),
                "service_id": str(service.id),
                "by_staff": StaffSlotsSerializer(by_staff, many=True).data,
            }
        )


def _earliest_per_start(by_staff):
    """One slot per distinct start time, from whoever offers it.

    Deduplicated because the client picking "anyone" should see 10:00 once, not
    once per stylist who happens to be free then.
    """
    seen = {}
    for entry in by_staff:
        for slot in entry["slots"]:
            seen.setdefault(slot.starts_at, slot)
    return [seen[key] for key in sorted(seen)]
