"""Every URL the frontend builds is one the backend routes.

Slice 11 found `web/app/m/[token]` — the manage link an SMS sends a client, the
one screen where they cancel or reschedule — asking for `/manage/<token>/`
instead of `/api/public/v1/manage/<token>/`. Every request it made had 404'd
since slice 7. Nothing noticed, and nothing could have: `render.test.tsx`
asserts on server-rendered markup, and markup does not contain a URL's
correctness.

That is the gap this file closes. It reads the actual TypeScript, extracts the
paths, and resolves each one against Django's real URLconf — so a wrong prefix
is a red build rather than a screen that renders beautifully and does nothing.

## Why it reads the source instead of running the app

A browser test would catch this and cost two servers, a headless Chrome and a
minute per run. The defect is a *string*, and a string can be checked in
milliseconds with nothing running. The things a browser catches that this
cannot — a credentialed cross-origin request, a missing CSRF cookie — are not
about which URLs exist, and `npm run smoke` covers those separately and
deliberately outside CI.

## The one assertion that makes it hold

`test_every_request_goes_through_a_known_helper`. Extracting call sites only
works if the extractor knows every way the frontend makes a request; a new
screen hand-rolling its own `fetch` would be invisible to the rest of this file
and would be exactly the shape of the bug it exists to catch. So the helpers are
enumerated, and any `fetch(` outside them fails until somebody either routes it
through a helper or adds it here on purpose.
"""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import Resolver404, resolve

pytestmark = pytest.mark.loadbearing

WEB = Path(settings.BASE_DIR) / "web"

#: Where the frontend's own code lives. `node_modules`, build output and the
#: generated token files are not ours and are not searched.
SOURCE_DIRS = ["app", "components", "lib", "packages/booking-core/src", "packages/widget/src"]

#: The three wrappers that build a request URL, and the file each lives in.
#:
#: Their bases are **not** written here. That was the first version of this
#: file and it was worthless: it recorded what each wrapper *should* prepend,
#: so when the prefix was deleted from the manage page the test went on
#: cheerfully asserting the prefix it had invented. It passed on the exact bug
#: it exists to catch, which is worse than not existing — it would have made
#: the next person confident.
#:
#: So the base is read out of the source instead, by expanding the wrapper's
#: own template. Delete `PUBLIC_API_PREFIX` from the manage page and its base
#: becomes empty, `/manage/x/cancel/` stops resolving, and the build goes red.
WRAPPERS = {
    # `shopScope` is a wrapper too: it prepends the org-and-shop scope and
    # returns a function, so its call sites read `shop("/walk-in/")` with the
    # endpoint as a literal. That shape exists so this file can see it.
    "lib/api.ts": ("api.get", "api.post", "shop", "postWithRetry"),
    "app/m/[token]/page.tsx": ("api",),
    "packages/booking-core/src/transport.ts": ("call",),
}

#: Where expansion stops. `API_BASE` and the transport's `baseUrl` are the
#: origin, which is empty because everything goes through the proxy in
#: `next.config.js` — see the note there.
TERMINALS = {"API_BASE": "", "baseUrl": ""}

#: `const NAME = `…`` and the call that actually issues the request.
CONST = re.compile(r"const\s+(\w+)\s*=\s*`([^`]*)`")
ISSUES_REQUEST = re.compile(r"(?:fetch|fetchImpl)\(\s*`\$\{([^{}]*)\}\$\{\w+\}`")

#: A UUID satisfies `<uuid:…>`, and also `<slug:…>` and `<str:…>`, whose
#: patterns both accept it. Tried in order so a route with a different converter
#: fails loudly here rather than being quietly skipped.
PLACEHOLDERS = ["0f14d0ab-9605-4a62-a9e4-5ed26688389b", "a-shop-slug", "1"]

#: `fetch(`, `api(`, `call(`, `api.get(`, `api.post(`, with a template or a
#: plain string as the first argument.
#: Whitespace is allowed around the dot because the frontend chains across
#: lines — `api\n  .get("/api/v1/auth/me/")` is how both boot screens are
#: written, and a regex that missed it would have silently covered nothing.
#: `test_the_known_endpoints_are_among_them` is what caught that.
CALL = re.compile(
    r"(?P<helper>fetch|call|shop|postWithRetry|api\s*\.\s*get|api\s*\.\s*post|api)"
    r"\(\s*(?P<quote>[`\"'])(?P<path>[^`\"']*)(?P=quote)"
)

#: An interpolation, and the base constants that are not path segments.
INTERPOLATION = re.compile(r"\$\{[^{}]*\}")


def public_api_prefix():
    """The prefix, from the module that exports it. Never from this file."""
    transport = (WEB / "packages/booking-core/src/transport.ts").read_text()
    match = re.search(r'export const PUBLIC_API_PREFIX = "([^"]*)"', transport)
    assert match, "booking-core no longer exports PUBLIC_API_PREFIX"
    return match[1]


def expand(template, consts, depth=0):
    """Resolve `${NAME}` through a file's own constants down to literals."""
    assert depth < 8, f"constants expand in a circle: {template}"
    out = template
    for name in re.findall(r"\$\{([^{}]*)\}", template):
        symbol = name.split(".")[0].strip()
        if symbol == "PUBLIC_API_PREFIX":
            value = public_api_prefix()
        elif symbol in TERMINALS:
            value = TERMINALS[symbol]
        elif symbol in consts:
            value = expand(consts[symbol], consts, depth + 1)
        else:
            continue
        out = out.replace(f"${{{name}}}", value)
    return out


#: `shopScope`'s body, so its base is derived rather than restated.
SCOPE = re.compile(r"export const shopScope\b[\s\S]{0,200}?`([^`]*)`")


def base_for(source, scoped=False):
    """What a request wrapper in this file prepends, read from the file itself.

    `scoped` picks `shopScope`'s base instead of the bare origin, because
    `lib/api.ts` defines two: `api.get` takes a whole path, and `shop(…)` adds
    the org-and-shop scope first.
    """
    consts = dict(CONST.findall(source))
    if scoped:
        match = SCOPE.search(source)
        return None if not match else expand(match[1].replace("${path}", ""), consts)
    match = ISSUES_REQUEST.search(source)
    if not match:
        return None
    return expand(f"${{{match[1]}}}", consts)


#: The helpers that carry the org-and-shop scope rather than a whole path.
SCOPED = {"shop"}


def wrapper_bases():
    """`{helper: base}`, every base derived from the source that defines it."""
    bases = {}
    for file, helpers in WRAPPERS.items():
        source = (WEB / file).read_text()
        for helper in helpers:
            base = base_for(source, scoped=helper in SCOPED)
            assert base is not None, f"{file} no longer defines the wrapper for {helper}()"
            bases[helper] = base
    return bases


def sources():
    for directory in SOURCE_DIRS:
        root = WEB / directory
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.ts")):
            if not path.name.endswith(".test.ts"):
                yield path
        yield from sorted(root.rglob("*.tsx"))


def code(text):
    """Comments out. This file's own prose names the paths it is looking for."""
    return re.sub(r"/\*[\s\S]*?\*/", "", re.sub(r"^\s*//.*$", "", text, flags=re.M))


def call_sites():
    """`(file, line, helper, raw path, that file's constants)` per request."""
    found = []
    for path in sources():
        source = code(path.read_text())
        consts = dict(CONST.findall(source))
        for match in CALL.finditer(source):
            line = source[: match.start()].count("\n") + 1
            # `api\n  .get` and `api.get` are the same helper.
            helper = re.sub(r"\s+", "", match["helper"])
            found.append((path.relative_to(WEB), line, helper, match["path"], consts))
    return found


def full_url(helper, path, consts, bases):
    """The whole URL a call site requests, or None if it is not a call site.

    Two shapes, and both are resolved from the source rather than assumed:

    - **Absolute.** `fetch(`${PUBLIC_ROOT}/shops/…`)` carries its own base, so
      the base is expanded through the file's constants. If somebody deletes
      the prefix from `PUBLIC_ROOT`, this expands to `/shops/…` and stops
      resolving — which is the whole point.
    - **Relative.** `api(`/manage/…`)` leans on its wrapper, so the wrapper's
      base is derived by reading the file that defines it.

    A template that is nothing but interpolations — `` `${ROOT}${path}` `` — is
    the wrapper itself rather than an endpoint, and is skipped: its argument is
    checked wherever it is called.
    """
    if re.fullmatch(r"(\$\{[^{}]*\})+", path):
        return None
    if path.startswith("${"):
        return expand(path, consts)
    base = bases.get(helper)
    return None if base is None else f"{base}{path}"


def resolvable(candidate):
    """Does this path resolve, for any placeholder the converters accept?"""
    bare = candidate.split("?")[0]
    for placeholder in PLACEHOLDERS:
        attempt = INTERPOLATION.sub(placeholder, bare)
        try:
            resolve(attempt)
        except Resolver404:
            continue
        return True
    return False


class TestTheExtractorSeesSomething:
    """If these fail, every assertion below is passing over an empty set."""

    def test_sources_were_found(self):
        assert list(sources())

    def test_call_sites_were_found(self):
        assert len(call_sites()) >= 10

    def test_the_known_endpoints_are_among_them(self):
        paths = " ".join(path for _, _, _, path, _ in call_sites())

        for expected in ("/shops/", "/holds/", "/manage/", "/api/v1/auth/me/"):
            assert expected in paths, expected


class TestEveryPathResolves:
    def test_no_frontend_request_is_for_a_url_the_backend_does_not_route(self):
        """The assertion this file exists for.

        A failure here reads as "this screen asks for a URL nothing serves",
        which is the sentence nobody got to read for four slices while the
        manage link 404'd.
        """
        bases = wrapper_bases()
        broken = []
        for file, line, helper, path, consts in call_sites():
            url = full_url(helper, path, consts, bases)
            if url is None:
                continue
            if not resolvable(url):
                broken.append(f"{file}:{line} {helper}(…) -> {url}")

        assert not broken, "frontend paths that no Django route serves:\n  " + "\n  ".join(broken)

    def test_the_manage_screens_paths_resolve_under_the_public_prefix(self):
        """Named on its own, because this is the one that was wrong.

        The SMS link is the client's only way to cancel or move a booking, and
        CLAUDE.md §12 makes it the whole session — there is no account to fall
        back to. A 404 here is a client who cannot cancel.
        """
        prefix = public_api_prefix()

        assert resolvable(f"{prefix}/manage/x/")
        assert resolvable(f"{prefix}/manage/x/cancel/")
        assert resolvable(f"{prefix}/manage/x/reschedule/")
        assert not resolvable("/manage/x/"), (
            "the bare path resolves, so this test could not have caught the bug it was written for"
        )


class TestTheExtractorCannotBeBypassed:
    def test_every_call_sites_url_can_actually_be_worked_out(self):
        """No request is opaque to the check above.

        A call site whose base cannot be expanded is one this file silently
        skips, and a silent skip is how a test ends up guarding nothing. So a
        path that still begins with an unresolved `${…}` after expansion —
        a base from a prop, an import, a function argument — fails here until
        the URL is made visible at the point it is requested.
        """
        bases = wrapper_bases()
        opaque = []
        for file, line, helper, path, consts in call_sites():
            url = full_url(helper, path, consts, bases)
            if url is None:
                continue
            if url.startswith("${"):
                opaque.append(f"{file}:{line} {helper}({path!r})")

        assert not opaque, (
            "requests whose base this check cannot see — build the path where it "
            "can be read:\n  " + "\n  ".join(opaque)
        )

    def test_the_manage_page_and_the_transport_derive_the_same_prefix(self):
        """The two consumers of the public API, each read from its own source.

        They disagreed for four slices and nothing said so. This is the
        assertion that would have — and unlike the first version of this file,
        neither side of it is a value this test invented.
        """
        manage = base_for((WEB / "app/m/[token]/page.tsx").read_text())
        transport = base_for((WEB / "packages/booking-core/src/transport.ts").read_text())

        assert manage == transport == public_api_prefix()
