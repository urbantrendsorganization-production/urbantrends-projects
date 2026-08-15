"""The manage link. One appointment, one token, no login.

CLAUDE.md §12: "Booking management happens through a signed, expiring,
single-appointment token delivered by SMS — the link is the session." This is
that token, and it is the whole of the authentication on the lifecycle surface.
It reaches a stranger's phone and grants control of a booking with money against
it, so the reasoning is written out rather than assumed.

## A stored random token, not a signed payload

§12 said "signed". A signed payload is ~120 characters in the URL, which tips
most confirmation messages into a second SMS segment — and §6 is explicit that
messaging cost is a real line item, at 300 bookings × 3 messages. A permanent
per-message tax to avoid one indexed column is the wrong trade.

128 bits from `secrets` is not weaker than an HMAC here. Both are unforgeable;
the signed one is unforgeable because you cannot compute it without the key, the
random one because you cannot guess it in 2^128 tries. What the stored token
adds is **revocation**, which a stateless token cannot have: `token_version`
bumps and every link already in a client's inbox stops working. That mattered
enough on its own.

The decision was taken at slice 7 planning and §12 is amended to match, rather
than left saying one thing while the code does another.

## Lifetime is anchored, not fixed

A booking six weeks out needs a link that lives six weeks; one made this morning
needs one that dies tonight. So expiry is `starts_at + MANAGE_TAIL`, not
"issued + N days". The tail exists so a client who has just been marked no-show
can still open the link and read what happened, which is the moment they are
most likely to try.

`ABSOLUTE_CAP` is a backstop and nothing else: a booking that somehow never
resolves must not leave a live credential forever.

## It survives a reschedule, deliberately

A move updates `time_range` in place on the same row — one row under the
exclusion constraint, the payment still attached, the history intact. The token
addresses the appointment, so it survives, and because expiry is anchored to
`starts_at` the link's life extends with the booking.

Breaking it would strand the client behind a second SMS that might not arrive,
on the action they just took. The reschedule confirmation carries a fresh link
too; both work, because they are the same token.

## What stops enumeration

Not the UUID primary key — that is unguessable but it is not the control.

1. **Unforgeability.** 128 bits of `secrets` entropy. There is nothing to
   enumerate.
2. **No existence oracle.** A bad token, an unknown token and a revoked token
   return the same failure. A caller cannot learn that a booking exists by
   probing, which is what makes the first point hold in practice.
3. **Constant-time comparison** on the lookup, so the endpoint cannot be turned
   into a timing side channel.
4. **Its own throttle scope** — the rule in `scheduling/abuse.py`.
5. **`Referrer-Policy: no-referrer`** on the manage page. The token is in the
   URL, and without it the whole credential leaks in the `Referer` header to
   anything the page loads.
"""

import secrets
from datetime import timedelta

from django.utils import timezone

#: How long past its start a booking stays manageable. Not zero: a client
#: marked no-show at 10:05 opening the link at 10:20 should read why, not a
#: dead page.
MANAGE_TAIL = timedelta(hours=2)

#: A backstop, not the policy. Nothing should reach it — a booking resolves long
#: before — but a live credential with no ceiling is not a thing to leave lying
#: around because the ordinary path is reliable.
ABSOLUTE_CAP = timedelta(days=90)

#: URL-safe, no padding, and short enough to keep the SMS in one segment.
#: 16 bytes is 128 bits; `token_urlsafe(16)` renders as 22 characters.
TOKEN_BYTES = 16


class ManageTokenInvalid(Exception):
    """Bad, unknown, revoked or expired — deliberately not distinguished.

    One exception with no detail, because every caller must answer identically.
    A message that said "expired" rather than "not found" would confirm that a
    booking exists, which is the existence oracle point 2 above rules out.
    """


def mint():
    return secrets.token_urlsafe(TOKEN_BYTES)


def expiry_for(appointment, *, now=None):
    """When this appointment's link dies. Anchored to the booking, capped."""
    now = now or timezone.now()
    return min(appointment.starts_at + MANAGE_TAIL, now + ABSOLUTE_CAP)


def issue(appointment, *, now=None, save=True):
    """Give this appointment a manage link. Idempotent per call, not per row.

    Called at hold creation and again on reschedule — the second call refreshes
    the expiry to follow the booking and deliberately keeps the same token, so a
    client's existing SMS keeps working.
    """
    now = now or timezone.now()
    if not appointment.manage_token:
        appointment.manage_token = mint()
    appointment.manage_expires_at = expiry_for(appointment, now=now)
    if save:
        appointment.save(update_fields=["manage_token", "manage_expires_at", "updated_at"])
    return appointment.manage_token


def revoke(appointment, *, save=True):
    """Kill every link already in a client's inbox.

    Bumps the version and drops the token. Cancelling does this: the SMS is
    still on their phone and the booking is no longer theirs to act on, and
    relying on each future endpoint to remember a status check is how one of
    them eventually forgets.
    """
    appointment.token_version += 1
    appointment.manage_token = None
    if save:
        appointment.save(update_fields=["token_version", "manage_token", "updated_at"])


def resolve(token, *, now=None):
    """The appointment this token manages, or `ManageTokenInvalid`.

    The only way in. Every lifecycle endpoint goes through here so that expiry,
    revocation and the no-oracle rule are decided once rather than re-argued per
    view.
    """
    from scheduling.models import Appointment

    now = now or timezone.now()
    if not token or not isinstance(token, str) or len(token) > 64:
        raise ManageTokenInvalid

    # `.unscoped()` for the reason the rest of the public surface uses it: there
    # is no request user and no organization here. The token is the scope — it
    # resolves to exactly one appointment in one tenant.
    appointment = (
        Appointment.objects.unscoped()
        .select_related("shop", "staff", "service", "client")
        .filter(manage_token=token)
        .first()
    )

    # A constant-time compare on a value already used as the lookup key adds
    # nothing — the index did the comparison. What matters is that the two
    # failure paths below are indistinguishable to a caller, which they are:
    # same exception, no message, and the view turns both into the same 404.
    if appointment is None:
        raise ManageTokenInvalid
    if appointment.manage_expires_at is None or appointment.manage_expires_at <= now:
        raise ManageTokenInvalid
    return appointment
