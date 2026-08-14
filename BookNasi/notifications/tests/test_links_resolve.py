"""Every link a message can emit has to land on a real page.

`booking_link` pointed at `/booking/<id>` for the whole of slice 6 and the
route did not exist, so every confirmation SMS carried a 404. Nothing caught
it: the Python side was correct in isolation, the route table lives in another
language in another directory, and no test spanned the two.

That is the gap this closes. It is a different kind of test from the rest of
this package — it reads the Next.js `app/` directory rather than exercising
Django — and it earns that because the failure it prevents is one a client
meets alone, holding the one message from us they kept, with money already
spent.

**Frontend routes, not Django ones.** `PUBLIC_BASE_URL` is the Next app, and
`reverse()` knows nothing about it. Next's file-system router is the authority,
so the route table is derived from the files: `app/booking/[id]/page.tsx` is
`/booking/<anything>`, and a directory with no `page.tsx` is not a route.

Deliberately not a network call. A test that fetched the URL would need the dev
server running, would pass or fail on whether someone had it up, and would be
skipped in CI within a week.
"""

import re
from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings

from notifications.service import queue_message, variables_for
from notifications.templates import RENDERERS, Template, render

pytestmark = pytest.mark.django_db

WEB_APP = Path(settings.BASE_DIR) / "web" / "app"

#: Anything that looks like an absolute URL in rendered copy.
URL_PATTERN = re.compile(r"https?://[^\s]+")


def next_routes():
    """The Next.js route table, as regexes, derived from the filesystem.

    `[id]` and `[slug]` become a single non-empty path segment. `[...rest]`
    becomes one or more. A directory without a `page.tsx` is not a route, which
    is exactly the mistake being guarded against.
    """
    routes = []
    for page in sorted(WEB_APP.rglob("page.tsx")):
        parts = page.relative_to(WEB_APP).parent.parts
        pattern = ""
        for part in parts:
            if part.startswith("(") and part.endswith(")"):
                continue  # a route group — organisational, not a path segment
            if part.startswith("[...") or part.startswith("[["):
                pattern += "/.+"
            elif part.startswith("[") and part.endswith("]"):
                pattern += "/[^/]+"
            else:
                pattern += "/" + re.escape(part)
        routes.append((page, re.compile(f"^{pattern or '/'}/?$")))
    return routes


def urls_in(text):
    return URL_PATTERN.findall(text)


def path_of(url):
    without_scheme = url.split("://", 1)[1]
    path = without_scheme[without_scheme.index("/") :] if "/" in without_scheme else "/"
    return path.split("?", 1)[0].split("#", 1)[0]


@pytest.fixture
def rendered_messages(held, shop_setup):
    """Every template, rendered from a real appointment.

    Driven off `RENDERERS` rather than a hand-written list so a template added
    without a route is caught by this test on the day it is added — which is the
    only day the fix is cheap.
    """
    out = {}
    for template in RENDERERS:
        variables = variables_for(held, template)
        # `slot_lost` needs a payment's support code; the others tolerate its
        # absence. Filled with a placeholder rather than skipped, because the
        # link is what is under test and it does not depend on the payment.
        variables.setdefault("support_code", "BK-TEST00")
        variables.setdefault("paid", "875")
        out[template] = render(template, variables)
    return out


class TestTheRouteTableItself:
    def test_the_web_app_directory_is_where_it_is_expected(self):
        """If this moves, every assertion below silently passes on an empty
        route table and the test becomes decoration."""
        assert WEB_APP.is_dir(), f"no Next app directory at {WEB_APP}"

    def test_some_routes_were_found(self):
        assert next_routes(), "derived an empty route table — the parser is wrong"


class TestEveryEmittedLinkResolves:
    def test_every_template_link_matches_a_real_page(self, rendered_messages):
        routes = next_routes()

        for template, body in rendered_messages.items():
            for url in urls_in(body):
                path = path_of(url)
                assert any(pattern.match(path) for _, pattern in routes), (
                    f"{template} emits {path}, which no page.tsx serves. "
                    f"Routes: {[p.pattern for _, p in routes]}"
                )

    def test_the_confirmation_carries_a_link_at_all(self, rendered_messages):
        """The one message a client keeps. A confirmation with no way back to
        the booking is how a cancel becomes a phone call."""
        assert urls_in(rendered_messages[Template.BOOKING_CONFIRMED])

    def test_a_link_to_a_route_that_does_not_exist_is_caught(self, held, monkeypatch):
        """The guard's own guard.

        Without this, a `next_routes()` that returned a catch-all — or an
        `urls_in` that found nothing — would make the test above pass for every
        possible link, including the 404 that prompted it.
        """
        from notifications import service

        monkeypatch.setattr(
            service,
            "booking_link",
            lambda appointment: f"{settings.PUBLIC_BASE_URL}/no-such-page/{appointment.pk}",
        )
        variables = service.variables_for(held, Template.BOOKING_CONFIRMED)
        variables.setdefault("paid", "875")
        body = render(Template.BOOKING_CONFIRMED, variables)
        routes = next_routes()

        paths = [path_of(url) for url in urls_in(body)]
        assert paths, "the fixture emitted no URL, so this proves nothing"
        assert not any(pattern.match(paths[0]) for _, pattern in routes)


class TestTheLinkPointsAtTheBooking:
    def test_the_confirmation_link_is_the_booking_page(self, held, rendered_messages):
        """Not just *a* route — the right one. `/book/<slug>` is also a real
        page, so matching the route table alone would accept a link that
        dropped the client back at the start of the flow."""
        body = rendered_messages[Template.BOOKING_CONFIRMED]
        path = path_of(urls_in(body)[0])

        assert path == f"/booking/{held.pk}"

    def test_a_queued_message_carries_the_same_link(self, held, console_messages):
        """`render` is only used by the SMS adapter. A WhatsApp adapter reads
        the variables, so the link has to be correct there too."""
        message = queue_message(held, Template.BOOKING_CONFIRMED)

        assert message.variables["link"] == f"{settings.PUBLIC_BASE_URL}/booking/{held.pk}"


class TestExpiryDoesNotChangeTheLink:
    def test_a_released_hold_still_links_somewhere_real(self, held, shop_setup):
        """The released message goes out when the slot is already gone, so its
        link is the one most likely to be followed late and least likely to be
        checked by hand."""
        from scheduling.holds import release_hold

        release_hold(held, now=held.hold_expires_at + timedelta(seconds=1), expired=True)
        held.refresh_from_db()

        variables = variables_for(held, Template.HOLD_RELEASED)
        body = render(Template.HOLD_RELEASED, variables)
        routes = next_routes()

        for url in urls_in(body):
            assert any(pattern.match(path_of(url)) for _, pattern in routes)
