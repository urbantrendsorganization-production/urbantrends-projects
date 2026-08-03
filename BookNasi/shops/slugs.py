"""Shop slugs are hostnames.

The booking page is `shopname.booknasi.co.ke`, so a shop slug is a DNS label in
a single global namespace. Two consequences that are easy to miss:

1. **Uniqueness is global, not per-org.** Two different organizations cannot
   both have a shop called "kilimani". This is the one place in the product
   where a tenant can collide with a tenant it cannot see.
2. **Some labels are not available**, because they are already in use by the
   platform or are conventionally expected to be. `api.booknasi.co.ke` must not
   be claimable by a salon.

Org slugs (slice 1) live in a *different* namespace — they are not hostnames and
are not reachable from outside — so the two do not need to be deduplicated
against each other.
"""

import re

from django.core.exceptions import ValidationError

# DNS labels: 63 characters, letters/digits/hyphens, no leading or trailing
# hyphen. Two characters minimum so single-letter labels stay available to the
# platform. Case is normalised rather than rejected — DNS is case-insensitive,
# so "Kilimani" and "kilimani" are the same host and refusing one would be
# pedantry rather than protection.
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$")
MAX_SLUG_LENGTH = 63

RESERVED_SLUGS = frozenset(
    {
        # Platform surfaces
        "www",
        "api",
        "admin",
        "app",
        "apps",
        "dashboard",
        "portal",
        "console",
        "manage",
        "settings",
        "config",
        "internal",
        "system",
        "sys",
        "root",
        # The product itself
        "booknasi",
        "book",
        "booking",
        "bookings",
        "widget",
        "embed",
        "site",
        "shop",
        "shops",
        "staff",
        "owner",
        "client",
        "clients",
        # Auth
        "auth",
        "oauth",
        "sso",
        "login",
        "signin",
        "sign-in",
        "signup",
        "sign-up",
        "register",
        "account",
        "accounts",
        "me",
        "my",
        "password",
        "reset",
        "verify",
        "authgate",
        # Money — these must never be spoofable
        "pay",
        "payment",
        "payments",
        "checkout",
        "billing",
        "invoice",
        "mpesa",
        "m-pesa",
        "daraja",
        "safaricom",
        "callback",
        "callbacks",
        "webhook",
        "webhooks",
        "refund",
        "refunds",
        # Mail and DNS, where a wrong answer breaks delivery
        "mail",
        "email",
        "webmail",
        "smtp",
        "imap",
        "pop",
        "pop3",
        "mx",
        "ns",
        "ns1",
        "ns2",
        "dns",
        "ftp",
        "autodiscover",
        "autoconfig",
        "_dmarc",
        "dkim",
        "spf",
        # Environments and infrastructure
        "staging",
        "stage",
        "dev",
        "development",
        "test",
        "testing",
        "qa",
        "demo",
        "sandbox",
        "preview",
        "beta",
        "alpha",
        "canary",
        "local",
        "localhost",
        "cdn",
        "static",
        "assets",
        "media",
        "img",
        "images",
        "files",
        "download",
        "downloads",
        "proxy",
        "gateway",
        "status",
        "health",
        "metrics",
        "monitor",
        "grafana",
        # Content
        "help",
        "support",
        "docs",
        "doc",
        "documentation",
        "blog",
        "news",
        "about",
        "contact",
        "legal",
        "privacy",
        "terms",
        "security",
        "abuse",
        "press",
        "careers",
        "pricing",
        # Reserved words that would read as bugs in a URL
        "null",
        "undefined",
        "none",
        "true",
        "false",
        "new",
        "edit",
        "delete",
        "create",
        "update",
        "public",
        "private",
    }
)


class SlugUnavailable(ValidationError):
    pass


def validate_shop_slug(value):
    """Raises ValidationError. Uniqueness is enforced separately, by the DB."""
    if not value:
        raise SlugUnavailable("A booking address is required.")

    slug = value.strip().lower()

    if len(slug) > MAX_SLUG_LENGTH:
        raise SlugUnavailable(f"A booking address can be at most {MAX_SLUG_LENGTH} characters.")
    if not SLUG_PATTERN.match(slug):
        raise SlugUnavailable(
            "A booking address may use lowercase letters, numbers and hyphens, "
            "must be at least two characters, and cannot start or end with a hyphen."
        )
    if slug.startswith("xn--"):
        # Punycode. Reserved so a shop cannot register something that renders as
        # another shop's name in a browser's address bar.
        raise SlugUnavailable("That booking address is not available.")
    if slug in RESERVED_SLUGS:
        raise SlugUnavailable(f"'{slug}' is reserved. Try something like '{slug}-salon'.")
    return slug


def suggest_slug(name, *, taken=frozenset()):
    """A starting point for the UI, never applied silently. See views."""
    from django.utils.text import slugify

    base = slugify(name)[:MAX_SLUG_LENGTH].strip("-") or "shop"
    if len(base) < 2:
        base = f"{base}-shop"

    candidate = base
    suffix = 2
    while candidate in RESERVED_SLUGS or candidate in taken:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate
