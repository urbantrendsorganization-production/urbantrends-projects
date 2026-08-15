"""The origin the frontend is served from must be one Django accepts writes from.

Slice 11's manual walk found that it was not. Signing in worked, and then the
first thing a signed-in person did — recording a walk-in — came back:

    CSRF Failed: Origin checking failed -
    http://localhost:3000 does not match any trusted origins.

`CSRF_TRUSTED_ORIGINS` was set only in `prod.py`, from an env var, so it was
empty in every other environment. Django compares the browser's `Origin` header
against the request's host for every unsafe method; behind the dev proxy and
behind Caddy those two are never the same string, so every authenticated write
was refused.

## Why 1305 tests did not see it

Two reasons, and both are about the seam rather than about the code.

`APIClient.force_authenticate` — which nearly every suite here uses — attaches a
user directly and **disables CSRF enforcement altogether**. It is the right tool
for testing a view's own logic and it is structurally incapable of seeing this.
And the test client sends no `Origin` header at all unless one is passed, so
even an unforced session client would sail past the check that fails in a
browser.

So the tests below do the two things the rest of the suite deliberately does
not: log in for a real session cookie, and send the header a browser sends.

## The negative case is the load-bearing one

`test_a_write_from_a_foreign_origin_is_still_refused` is what stops this file
being "fixed" one day by turning CSRF off. A green suite with that test deleted
would mean something very different from a green suite with it passing.
"""

import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework.test import APIClient

pytestmark = [pytest.mark.django_db, pytest.mark.loadbearing]

PASSWORD = "correct-horse-battery"


@pytest.fixture
def browserish(shop_setup):
    """A client that behaves like a browser: real session, CSRF enforced.

    `enforce_csrf_checks=True` is the opposite of what the rest of the suite
    wants and the whole point here.
    """
    client = APIClient(enforce_csrf_checks=True)
    assert client.login(phone=shop_setup.org.stylist.phone, password=PASSWORD)
    # Django only sets the cookie when something asks for a token, which is what
    # this endpoint is for. The frontend calls it lazily before its first write.
    client.get(reverse("accounts:csrf"))
    return client


@pytest.fixture
def walk_in_url(shop_setup):
    return reverse(
        "scheduling:walk-in",
        kwargs={"org_id": shop_setup.organization.id, "shop_id": shop_setup.shop.id},
    )


def _post(client, url, payload, *, origin):
    return client.post(
        url,
        payload,
        format="json",
        HTTP_ORIGIN=origin,
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )


class TestTheFrontendsOwnOrigin:
    def test_public_base_url_is_trusted(self):
        """The address in every SMS is the address the staff app loads from, so
        an origin we send clients to is an origin we take writes from. Defaulted
        rather than configured, because a deploy that sets one and forgets the
        other is the whole defect."""
        assert settings.PUBLIC_BASE_URL in settings.CSRF_TRUSTED_ORIGINS

    def test_an_authenticated_write_from_that_origin_is_accepted(
        self, browserish, shop_setup, walk_in_url
    ):
        """The walk-in that failed in the browser. Asserted as "not refused for
        a CSRF reason" rather than as 201, so this test keeps reporting on the
        thing it is about even if the endpoint's success shape changes."""
        response = _post(
            browserish,
            walk_in_url,
            {"service": str(shop_setup.shave.id), "staff": str(shop_setup.grace.id)},
            origin=settings.PUBLIC_BASE_URL,
        )

        assert response.status_code != 403, response.data
        assert response.status_code == 201, response.data

    def test_a_write_from_a_foreign_origin_is_still_refused(
        self, browserish, shop_setup, walk_in_url
    ):
        """The guard that keeps the one above honest.

        Without this, the cheapest way to make the previous test pass is to stop
        checking origins at all, and nothing would say so. `/api/v1/` is the
        surface that reads a shop's takings; it is same-origin by design and
        `core/cors.py` gives it no CORS headers, so this refusal is the control
        that pairs with that absence."""
        response = _post(
            browserish,
            walk_in_url,
            {"service": str(shop_setup.shave.id), "staff": str(shop_setup.grace.id)},
            origin="https://not-booknasi.example",
        )

        assert response.status_code == 403


class TestItCannotBeNarrowedByAccident:
    def test_no_settings_module_overrides_it_with_an_empty_default(self):
        """`prod.py` used to re-read the env var with a default of `()`.

        That line looked like it was handling production and in fact meant
        production rejected every authenticated write whenever the variable was
        unset — the same failure as development, wearing a reassuring shape. It
        is deleted, and this asserts nothing puts it back: read the settings
        source rather than the imported value, because an override in a module
        this test does not import would be invisible to `settings`."""
        import pathlib

        settings_dir = pathlib.Path(settings.BASE_DIR) / "config" / "settings"
        assignments = [
            (path.name, line.strip())
            for path in sorted(settings_dir.glob("*.py"))
            for line in path.read_text().splitlines()
            if line.startswith("CSRF_TRUSTED_ORIGINS")
        ]

        assert assignments == [
            (
                "base.py",
                'CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", '
                "default=(PUBLIC_BASE_URL,))",
            )
        ], assignments
