"""The widget's cross-origin access, and the two things it must never grant.

Slice 10 puts the booking flow inside somebody else's page, which makes every
call it makes a cross-origin one. `core/cors.py` is what lets those through.

Most of this file asserts **absences**, which is the reason it exists at all: a
header that is not set leaves no trace in a diff, in a log, or in a review. The
CORS mistake with teeth — reflect the caller's origin, then allow
credentials — is two lines nobody wrote, and it is indistinguishable from
correct code by inspection. So it is pinned here instead.

The other half is the opposite mistake: applying the headers too widely.
`/api/v1/` is the org-scoped surface, session-authenticated and same-origin, and
the same-origin policy is what stands between a stylist's browser and a page
that reads their organization's takings. Widening CORS to reach it would undo
`core/tenancy.py` from the outside.
"""

import pytest
from django.core.cache import cache
from django.urls import get_resolver, reverse

from core.cors import ALLOWED_HEADERS, ALLOWED_METHODS, PUBLIC_PREFIX
from core.exceptions import PUBLIC_NOT_FOUND

pytestmark = [pytest.mark.loadbearing, pytest.mark.django_db]

#: One endpoint squeezed to a rate a test can reach. Every other scope is absent
#: rather than loosened, so an endpoint that starts throttling in this file is a
#: scope that changed name — which is worth failing over.
ONE_PER_DAY = {"shop-read": "1/day"}

ORIGIN = "https://mint-braids.co.ke"
#: Deliberately not a shop's domain. Reflection is tested by sending a hostile
#: origin and looking for it in the answer.
HOSTILE = "https://evil.example"

ALLOW_ORIGIN = "Access-Control-Allow-Origin"
ALLOW_CREDENTIALS = "Access-Control-Allow-Credentials"


def public_routes():
    """Every concrete path under the public prefix, walked from the URLconf.

    Walked rather than listed for the same reason `test_throttle_scopes.py`
    walks it: a route added in a later slice is covered on the day it is routed,
    not on the day somebody remembers this file.
    """
    found = []
    for pattern in get_resolver().url_patterns:
        _walk(pattern, "", found)
    return [route for route in found if route.startswith(PUBLIC_PREFIX.lstrip("/"))]


def _walk(pattern, prefix, found):
    route = prefix + str(getattr(pattern, "pattern", ""))
    if hasattr(pattern, "url_patterns"):
        for child in pattern.url_patterns:
            _walk(child, route, found)
        return
    found.append(route)


class TestTheSurfaceIsWhatWeThinkItIs:
    """If these fail, every assertion below is passing over an empty set."""

    def test_the_public_routes_were_found(self):
        assert public_routes()

    def test_they_are_the_booking_endpoints(self):
        routes = " ".join(public_routes())

        for expected in ("shops/", "holds/", "availability/", "manage/"):
            assert expected in routes, expected


class TestTheWidgetCanCall:
    def test_a_public_read_carries_the_header(self, client, shop_setup):
        url = reverse("public_api:shop-detail", args=[shop_setup.shop.slug])

        response = client.get(url, HTTP_ORIGIN=ORIGIN)

        assert response.status_code == 200
        assert response[ALLOW_ORIGIN] == "*"

    def test_a_preflight_is_answered(self, client, shop_setup):
        url = reverse("public_api:hold-create", args=[shop_setup.shop.slug])

        response = client.options(url, HTTP_ORIGIN=ORIGIN)

        assert response.status_code == 204
        assert response[ALLOW_ORIGIN] == "*"
        assert response["Access-Control-Allow-Methods"] == ALLOWED_METHODS
        assert response["Access-Control-Allow-Headers"] == ALLOWED_HEADERS
        assert response["Access-Control-Max-Age"]

    def test_the_preflight_answer_does_not_depend_on_the_route(self, client):
        """A preflight is a question about the policy, not about the resource.

        Which is why it is answered in the middleware and not in a view: routing
        it would mean every public view growing an `options()` that repeats the
        policy, and the eleventh one would forget.
        """
        response = client.options("/api/public/v1/no-such-endpoint/", HTTP_ORIGIN=ORIGIN)

        assert response.status_code == 204
        assert response[ALLOW_ORIGIN] == "*"

    def test_every_public_route_is_inside_the_prefix_the_middleware_matches(self):
        """The middleware matches one literal prefix. This is the assertion that
        a route added under a *different* public prefix would fail."""
        for route in public_routes():
            assert f"/{route}".startswith(PUBLIC_PREFIX), route


class TestTheTwoRulesThatAreNotNegotiable:
    """Reflection and credentials. Either alone is survivable; together they are
    a page on the internet reading whatever the victim's cookie can reach."""

    def test_the_origin_is_never_reflected(self, client, shop_setup):
        url = reverse("public_api:shop-detail", args=[shop_setup.shop.slug])

        response = client.get(url, HTTP_ORIGIN=HOSTILE)

        assert response[ALLOW_ORIGIN] == "*"
        assert HOSTILE not in response[ALLOW_ORIGIN]

    def test_a_preflight_does_not_reflect_either(self, client):
        response = client.options("/api/public/v1/shops/anything/", HTTP_ORIGIN=HOSTILE)

        assert response[ALLOW_ORIGIN] == "*"

    def test_credentials_are_never_allowed_on_a_read(self, client, shop_setup):
        url = reverse("public_api:shop-detail", args=[shop_setup.shop.slug])

        response = client.get(url, HTTP_ORIGIN=ORIGIN)

        assert ALLOW_CREDENTIALS not in response

    def test_credentials_are_never_allowed_on_a_preflight(self, client):
        response = client.options("/api/public/v1/shops/x/", HTTP_ORIGIN=ORIGIN)

        assert ALLOW_CREDENTIALS not in response

    def test_the_complete_set_of_headers_the_middleware_can_set(self):
        """Stated exhaustively, by reading the module rather than a response.

        A response assertion can only speak for the responses a test reaches.
        This speaks for all of them: a header can only be set by naming it in an
        assignment, so the set of names assigned in the file *is* the set of
        headers this middleware is capable of adding. `Allow-Credentials` is not
        in it, and neither is anything else nobody decided on.

        Read from the syntax tree rather than grepped, because the module
        explains the credentials hazard by name and at length — a check that
        cannot tell code from a comment about code gets weakened until it means
        nothing, which is the lesson `check-no-framework.mjs` and
        `test_org_scoped_manager_guard.py` each learned separately.
        """
        import ast
        import inspect

        from core import cors

        tree = ast.parse(inspect.getsource(cors))
        assigned = {
            node.targets[0].slice.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Subscript)
            and isinstance(node.targets[0].slice, ast.Constant)
        }

        assert assigned == {
            "Access-Control-Allow-Origin",
            "Access-Control-Allow-Methods",
            "Access-Control-Allow-Headers",
            "Access-Control-Max-Age",
        }

    def test_csrf_is_not_an_allowed_header(self, client):
        """The widget sends no cookie, so it has no CSRF token to send. A widget
        that tried should fail its preflight loudly rather than quietly acquire
        a credential-shaped header on a non-credentialed request."""
        response = client.options("/api/public/v1/shops/x/", HTTP_ORIGIN=ORIGIN)

        assert "csrf" not in response["Access-Control-Allow-Headers"].lower()

    def test_only_the_methods_that_exist_are_advertised(self, client):
        """A method advertised as allowed that answers 405 is a lie told in a
        header. Nothing on this surface takes PUT, PATCH or DELETE."""
        response = client.options("/api/public/v1/shops/x/", HTTP_ORIGIN=ORIGIN)
        allowed = response["Access-Control-Allow-Methods"]

        assert "GET" in allowed and "POST" in allowed and "OPTIONS" in allowed
        for absent in ("PUT", "PATCH", "DELETE"):
            assert absent not in allowed


class TestTheAuthenticatedSurfaceGetsNothing:
    """`/api/v1/` is org-scoped and session-authenticated. The same-origin
    policy is a control there, not an obstacle."""

    def test_an_org_scoped_route_carries_no_cors_header(self, api_client, shop_setup):
        api_client.force_authenticate(shop_setup.org.owner)
        url = reverse("reporting:report", args=[shop_setup.organization.id])

        response = api_client.get(url, HTTP_ORIGIN=HOSTILE)

        assert response.status_code == 200
        assert ALLOW_ORIGIN not in response

    def test_an_org_scoped_preflight_is_not_answered_by_the_middleware(self, client, shop_setup):
        url = reverse("reporting:report", args=[shop_setup.organization.id])

        response = client.options(url, HTTP_ORIGIN=HOSTILE)

        assert ALLOW_ORIGIN not in response
        assert response.status_code != 204

    def test_the_admin_carries_no_cors_header(self, client):
        response = client.get("/admin/", HTTP_ORIGIN=HOSTILE)

        assert ALLOW_ORIGIN not in response

    def test_safaricoms_callback_carries_no_cors_header(self, client):
        """Not part of the public booking API — no integrator calls it, and no
        browser should be able to. See `config/urls.py`."""
        response = client.post("/api/mpesa/nonsense/", HTTP_ORIGIN=HOSTILE)

        assert ALLOW_ORIGIN not in response


class TestErrorsAreStillReadable:
    """A response the browser discards is a response the widget cannot classify.

    `flow.classify` branches on `status`: 409 means the slot went, 429 means
    wait, 4xx means the request was wrong, and no status at all means offline.
    An error without the header arrives as the last of those, so a client who
    hit a rate limit is told to check their data connection.
    """

    def test_a_404_carries_the_header(self, client):
        response = client.get("/api/public/v1/shops/no-such-shop/", HTTP_ORIGIN=ORIGIN)

        assert response.status_code == 404
        assert response[ALLOW_ORIGIN] == "*"

    def test_an_unrouted_public_path_carries_the_header(self, client):
        """Produced by the resolver, without a view. The middleware's response
        phase still runs, which is why the header is applied there."""
        response = client.get("/api/public/v1/not-a-thing/", HTTP_ORIGIN=ORIGIN)

        assert response.status_code == 404
        assert response[ALLOW_ORIGIN] == "*"

    def test_a_429_carries_the_header(self, client, shop_setup, monkeypatch):
        """The case that motivated putting the header in the response phase.

        Without it the client is told "No connection. Check your data and try
        again" while the truth is a rate limit — and they retry, immediately,
        which is the one thing that cannot help.

        The rate is patched on the throttle class rather than through
        `override_settings`: DRF reads `DEFAULT_THROTTLE_RATES` into
        `SimpleRateThrottle.THROTTLE_RATES` once, at import, so a settings
        override here would be accepted, ignored, and leave a test that passes
        because nothing was ever throttled.
        """
        from rest_framework.throttling import SimpleRateThrottle

        monkeypatch.setattr(SimpleRateThrottle, "THROTTLE_RATES", ONE_PER_DAY)
        cache.clear()
        url = reverse("public_api:shop-detail", args=[shop_setup.shop.slug])

        assert client.get(url, HTTP_ORIGIN=ORIGIN).status_code == 200
        throttled = client.get(url, HTTP_ORIGIN=ORIGIN)

        assert throttled.status_code == 429
        assert throttled[ALLOW_ORIGIN] == "*"


class TestA404IsNotOrmSpeak:
    """Slice 10 made this visible rather than creating it.

    `get_object_or_404` writes "No Shop matches the given query.", DRF carries
    it into the response body, and the flow puts `detail` on the screen. Inside
    the widget that sentence appears in a salon's own website, naming a database
    model, to a client who arrived from a WhatsApp link.
    """

    def test_a_public_404_says_something_a_client_can_act_on(self, client):
        response = client.get("/api/public/v1/shops/no-such-shop/", HTTP_ORIGIN=ORIGIN)

        assert response.status_code == 404
        assert response.json()["detail"] == PUBLIC_NOT_FOUND

    def test_it_names_no_model(self, client, shop_setup):
        for url in (
            "/api/public/v1/shops/no-such-shop/",
            "/api/public/v1/holds/00000000-0000-0000-0000-000000000000/",
            "/api/public/v1/manage/not-a-real-token/",
        ):
            body = client.get(url, HTTP_ORIGIN=ORIGIN).json()

            assert "query" not in body.get("detail", ""), url
            for model in ("Shop", "Appointment", "Service", "Staff"):
                assert model not in body.get("detail", ""), (url, model)

    def test_it_does_not_say_which_thing_was_missing(self, client):
        """`lifecycle_views` returns one 404 for a malformed token and a wrong
        one, so the endpoint is not an existence oracle. A message that told
        them apart would hand back what the status code withholds."""
        wrong = client.get("/api/public/v1/manage/aaaabbbbccccdddd/").json()
        malformed = client.get("/api/public/v1/manage/!!!/").json()

        assert wrong == malformed

    def test_the_authenticated_surface_keeps_its_own_wording(self, api_client, shop_setup):
        """`/api/v1/` 404s are read by staff, owners and us. Django's sentence is
        useful there, and `reporting/views.py` writes its own on purpose."""
        api_client.force_authenticate(shop_setup.org.owner)
        url = reverse("reporting:report", args=[shop_setup.organization.id])

        body = api_client.get(url, {"shop": "not-a-uuid"}).json()

        assert body["detail"] != PUBLIC_NOT_FOUND
