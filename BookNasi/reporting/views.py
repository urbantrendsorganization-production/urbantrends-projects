"""One endpoint, one screen.

`GET /api/v1/orgs/<org>/report/?from=&to=&shop=`

The design's Overview is cards *and* the revenue-per-staff table *and* the load
meters across shops, and an owner opens it once. Splitting it into three
requests would put two of them on the critical path of a screen that already
waits on a range scan, for no gain — nothing on this page is independently
refreshable.

## Owners and managers only

`managing_roles_required = True`, which is the one access decision this slice
makes and it follows directly from CLAUDE.md §12: "Staff see only their own
day." Per-person logins exist so revenue can be attributed per stylist, and a
stylist who can read the attribution can read everyone else's pay. The staff
day view stays where it is; there is no read here for a `Staff` role and no
query parameter that produces one.

The refusal is a 403 rather than a 404, unlike the org lookup itself. Membership
of the organization has already been established by that point — the user knows
it exists because they are in it — so there is nothing left to conceal, and a
404 would tell a manager that the reports feature does not exist rather than
that they may not read it.

## No throttle scope

`core/tests/test_throttle_scopes.py` requires one on every route under
`api/public/`. This is not one: it is authenticated, session-bound and behind a
role check, so the bound that matters is the login rather than the IP. The rule
in `scheduling/abuse.py` is about carrier-grade NAT on the unauthenticated
surface.

`?fresh=1` skips the cache and is therefore the most expensive request here.
It is bounded on both sides — an owner or manager of that organization only,
and `MAX_DAYS` on the range — so the worst case is somebody re-running their own
scan. Worth naming rather than leaving to be discovered: if this ever needs a
limit, it is a per-user throttle and not a per-IP one.
"""

from django.http import Http404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.tenancy import OrgScopedMixin
from reporting import cache
from reporting.period import PeriodInvalid, parse_period
from reporting.serializers import report_payload
from shops.models import Shop


class ReportView(OrgScopedMixin, APIView):
    """The owner dashboard, in one response."""

    managing_roles_required = True

    def get(self, request, org_id):
        try:
            period = parse_period(request.query_params)
        except PeriodInvalid as exc:
            return Response({"period": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)

        all_shops, shop_filter = self.shops_in_scope(request)
        shops = [shop_filter] if shop_filter else all_shops
        if not all_shops:
            # An organization with no shops yet. An empty report is the right
            # answer rather than a 404 — the owner has signed up and has not
            # finished onboarding, and a dashboard that 404s at that moment
            # reads as broken software rather than as an empty shop.
            return Response(_empty(self.organization, period))

        report = cache.report_for(
            organization=self.organization,
            shops=shops,
            period=period,
            now=timezone.now(),
            today_shops=all_shops,
            use_cache=request.query_params.get("fresh") != "1",
        )
        return Response(
            report_payload(
                report, organization=self.organization, shops=all_shops, shop_filter=shop_filter
            )
        )

    def shops_in_scope(self, request):
        """`(every shop in the organization, the one named by ?shop= or None)`.

        Both, deliberately. The design's shop switcher shows today's load for
        each branch and sits on the same screen, so narrowing the *aggregates*
        to one shop must not empty the list or blank the other meters — that is
        what lets the switcher be drawn without a second request.
        """
        all_shops = list(Shop.objects.for_org(self.organization).order_by("name"))
        requested = request.query_params.get("shop")
        if not requested:
            return all_shops, None
        # Matched against the list already fetched rather than queried again.
        # One less round trip, and it makes a malformed `?shop=` a 404 like any
        # other unknown id — passing it to the ORM would raise a UUID
        # `ValidationError` from inside a read, which is a 500 for a typo.
        shop = next((row for row in all_shops if str(row.id) == requested), None)
        if shop is None:
            raise Http404("No such shop in this organization.")
        return all_shops, shop


def _empty(organization, period):
    from reporting.metrics import Clients, Money, Outcomes, Report

    report = Report(
        period=period,
        outcomes=Outcomes(),
        previous=Outcomes(),
        money=Money(),
        clients=Clients(),
    )
    return report_payload(report, organization=organization, shops=[], shop_filter=None)
