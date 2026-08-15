"""Every public endpoint carries its own throttle scope.

The rule, and the two slices that taught it to us, are in `scheduling/abuse.py`.
The short version: Safaricom and Airtel put large numbers of subscribers behind
carrier-grade NAT, so a *shared* scope is not "these endpoints together get
N/hour" — it is "one client's traffic can exhaust the allowance of every
stranger on their operator's NAT pool", and the 429 lands on whichever endpoint
they touch next rather than the noisy one.

Slice 5 set the per-IP hold limit tight enough to refuse honest clients. Slice 6
put a 3-second poll on `hold-detail` inside the shared `public-read` scope, so
two clients behind one NAT address 429'd each other mid-payment — and a 429
there freezes the STK screen with the money already gone. Same mistake, new
place, and neither was caught by a test.

This is that test. It walks the real URLconf rather than a hand-kept list, so an
endpoint added in a later slice is covered on the day it is routed.
"""

import pytest
from django.conf import settings
from django.urls import get_resolver

pytestmark = pytest.mark.loadbearing

#: The prefix every unauthenticated route sits under. Anything outside it is
#: staff- or owner-facing and authenticated, and bounded by a session rather
#: than by an IP.
PUBLIC_PREFIX = "api/public/"


def public_views():
    """Every view class routed under the public prefix, with its route."""
    found = {}
    for pattern in get_resolver().url_patterns:
        _walk(pattern, "", found)
    return {route: view for route, view in found.items() if route.startswith(PUBLIC_PREFIX)}


def _walk(pattern, prefix, found):
    route = prefix + str(getattr(pattern, "pattern", ""))
    if hasattr(pattern, "url_patterns"):
        for child in pattern.url_patterns:
            _walk(child, route, found)
        return
    view = getattr(pattern.callback, "view_class", None)
    if view is not None:
        found[route] = view


class TestThePublicSurfaceIsDiscoverable:
    """If these fail, every assertion below is passing over an empty set."""

    def test_public_routes_were_found(self):
        assert public_views(), "found no routes under the public prefix"

    def test_the_known_endpoints_are_among_them(self):
        routes = " ".join(public_views())

        for expected in ("holds", "availability", "services", "staff"):
            assert expected in routes, f"{expected} is missing from the public surface"


class TestEveryPublicEndpointHasItsOwnScope:
    def test_none_are_missing_a_scope(self):
        missing = {
            route: view.__name__
            for route, view in public_views().items()
            if not getattr(view, "throttle_scope", None)
        }

        assert not missing, (
            "public endpoints with no throttle scope of their own: "
            f"{missing}. See the rule in scheduling/abuse.py — declare one, "
            "and add its rate to DEFAULT_THROTTLE_RATES."
        )

    def test_every_scope_has_a_rate(self):
        """A scope with no rate is not throttled at all. DRF resolves the rate
        by name and silently applies none when the name is absent, so a typo
        reads as a working throttle and is not one."""
        rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        unrated = {
            route: view.throttle_scope
            for route, view in public_views().items()
            if getattr(view, "throttle_scope", None) and view.throttle_scope not in rates
        }

        assert not unrated, f"scopes with no configured rate: {unrated}"

    def test_no_two_endpoints_share_a_scope(self):
        """The rule itself.

        Sharing is what made slice 6's poll starve the shop and availability
        reads. Two endpoints that share a budget are one endpoint as far as a
        client behind CGNAT is concerned.

        Subclassed views are excluded by identity, not by name: `HoldReleaseView`
        extends `HoldDetailView` for its lookup and legitimately has its own
        scope, but a view that inherited one by accident would be a *different*
        class reporting the *same* scope, which is exactly what this catches.
        """
        seen = {}
        clashes = []
        for _route, view in sorted(public_views().items()):
            scope = getattr(view, "throttle_scope", None)
            if scope is None:
                continue  # covered by the test above
            if scope in seen and seen[scope] is not view:
                clashes.append((scope, seen[scope].__name__, view.__name__))
            seen.setdefault(scope, view)

        assert not clashes, (
            "these endpoints share a throttle scope: "
            + "; ".join(f"{s}: {a} and {b}" for s, a, b in clashes)
            + ". See scheduling/abuse.py."
        )

    def test_the_mixin_supplies_no_default(self):
        """The mechanism behind the rule.

        A default is how a scope gets inherited by accident — which is precisely
        how `HoldDetailView` ended up inside `public-read`. With `None`, a
        forgotten scope is an *unthrottled* endpoint, which the test above
        fails on loudly, rather than a silently shared budget that fails in
        production under someone else's traffic.
        """
        from public_api.views import PublicViewMixin

        assert PublicViewMixin.throttle_scope is None

    def test_the_polled_endpoint_is_not_on_a_read_budget(self):
        """The specific regression. `hold-read` is polled every three seconds
        for the life of a hold; the once-per-booking reads are not."""
        rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]

        def per_hour(scope):
            count, _, _ = rates[scope].partition("/")
            return int(count)

        assert per_hour("hold-read") > per_hour("shop-read") * 4
