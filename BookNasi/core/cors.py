"""Cross-origin access to the public booking API, and nothing else.

Slice 10 is the embeddable widget. It runs as a script inside somebody else's
page — a `/site` template on `mint-braids.co.ke`, a Squarespace site, a
one-page shop site a cousin built — and from there it calls
`api.booknasi.co.ke/api/public/v1/...`. That is a cross-origin request, so
without these headers the browser refuses every read before it leaves the
machine and the widget is a blank box. CLAUDE.md §1 says to build every API as
if a third party will integrate it; this is the header that makes that true in a
browser rather than only in a server-side HTTP client.

## Why this is written here instead of installed

`django-cors-headers` is the obvious answer and it is a good package. What it
sells is configurability: regexes, per-view decorators, allowlists, credential
modes, header lists. Every one of those is a lever, and the levers are the
hazard — the CORS mistakes that matter are all *configuration* mistakes, and
the worst of them (reflect the caller's origin, then allow credentials) is two
settings away in any installation of it.

The policy this product needs has no levers at all. One path prefix. Three
methods. One request header. Credentials never. Written out it is the code
below, it fits on a screen, and every refusal it makes is visible in the file
rather than in the interaction between four settings and a package default.
CLAUDE.md §11's rule is about not taking a dependency for something already
solved; this is the narrower case where the dependency's whole value is
flexibility we would spend the slice locking back down.

## Why `*` and not an allowlist of host domains

An allowlist reads safer and is not. Three reasons, in order of weight:

1. **It protects nothing here.** These endpoints are unauthenticated, take no
   cookie, and return a shop's public booking page — the same data the shop
   prints on a poster. Anything an attacker could read through a browser they
   can already read with one line of `curl`, where CORS does not exist. A
   header that stops honest browsers and not dishonest scripts is theatre.

2. **It is a support burden that fails at the worst time.** Every shop that
   moves domain, adds `www.`, or embeds on a staging host would be a support
   ticket, and the failure arrives as a dead booking widget on a Saturday
   morning with nothing in the shop's own logs to explain it.

3. **What actually bounds abuse is elsewhere and already built.** The per-phone
   hold ceilings in `scheduling/abuse.py` and the per-endpoint throttle scopes
   in settings are the controls. An origin string chosen by the caller was
   never going to be one.

So: a static `*`, no `Vary: Origin` — there is nothing origin-dependent in the
response to vary on, and a `Vary` that lies costs every CDN edge its cache key.

## The two rules that are not negotiable

**Credentials are never allowed and the origin is never reflected.** Together
those two are the CORS mistake with teeth: reflecting the caller's origin *and*
setting `Access-Control-Allow-Credentials: true` turns any page on the internet
into a logged-in reader of whatever the victim's cookie can reach. Neither is
here, and `core/tests/test_cors.py` asserts the absence of both rather than
trusting it, because their absence is invisible in review — you cannot see a
header that is not there.

**Nothing outside `PUBLIC_PREFIX` gets a header.** `/api/v1/` is the org-scoped
surface: the owner dashboard, staff day view, shop settings, every reason
`core/tenancy.py` exists. It is session-authenticated and same-origin, and the
same-origin policy is the thing standing between a stylist's browser and a page
that reads their organization's takings. This middleware must never widen it,
and there is deliberately no setting that would let it.

## Why the headers go on error responses too

A 429 from `hold-create` without `Access-Control-Allow-Origin` is not a 429 the
widget can see. The browser discards the response and reports a network error,
so the client is told "no connection" when the truth is "too many holds from
this number, wait a minute" — the flow classifies on `status`, and a status it
never receives is a status it cannot classify. So the header is applied in the
response phase, to whatever came back, including the ones Django produced
without reaching a view.
"""

from django.http import HttpResponse

#: Everything under here is the unauthenticated booking surface — see
#: `public_api/views.py`. Matched as a literal prefix rather than a regex: a
#: regex is where an allowlist grows, and `/api/public/` is one string.
PUBLIC_PREFIX = "/api/public/"

#: The three the widget uses. Reads are GET, every write on this surface is a
#: POST (hold create, release, resend, cancel, reschedule, re-point), and
#: OPTIONS is the preflight itself. No PUT, PATCH or DELETE — not because they
#: are dangerous, but because nothing on this surface answers them, and a method
#: advertised as allowed that returns 405 is a lie told in a header.
ALLOWED_METHODS = "GET, POST, OPTIONS"

#: `Content-Type`, and nothing else. Notably **not** `X-CSRFToken`: the widget
#: sends no cookie, so it has no CSRF token to send, and a widget that tried
#: would fail its preflight loudly here instead of quietly acquiring a
#: credential-shaped header on a non-credentialed request.
ALLOWED_HEADERS = "Content-Type"

#: A day. Chrome caps preflight caching lower than this and Firefox does not;
#: both are free to ignore it entirely. It is worth setting anyway — the client
#: is on 3G and a preflight before every POST is a whole extra round trip at the
#: moment they are trying to pay.
MAX_AGE_SECONDS = "86400"


def _is_public(path):
    return path.startswith(PUBLIC_PREFIX)


class PublicApiCorsMiddleware:
    """Adds the headers to `/api/public/`, and answers its preflights."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "OPTIONS" and _is_public(request.path):
            # Answered here rather than in a view. A preflight is a question
            # about the *policy*, not about the resource, and routing it to a
            # view would mean every public view growing an `options()` that
            # repeats this file. It also means a preflight for a path that does
            # not exist gets the policy rather than a 404 — which is correct: a
            # browser asking whether it may POST somewhere is entitled to the
            # answer before it finds out the URL is wrong.
            response = HttpResponse(status=204)
            response["Access-Control-Allow-Methods"] = ALLOWED_METHODS
            response["Access-Control-Allow-Headers"] = ALLOWED_HEADERS
            response["Access-Control-Max-Age"] = MAX_AGE_SECONDS
        else:
            response = self.get_response(request)

        if _is_public(request.path):
            # Static, never reflected from the request. See the module docstring:
            # reflection is half of the mistake, and `Allow-Credentials` — the
            # other half — is not set anywhere in this file on purpose.
            response["Access-Control-Allow-Origin"] = "*"

        return response
