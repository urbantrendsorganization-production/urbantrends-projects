"""The reference a client reads down a phone line.

The design draws `BK-40219` on screen 8. Five digits is the wrong shape for
what this has to do, in two ways that matter:

- **Collisions.** 100,000 codes over the life of the product is not enough. Two
  live disputes sharing a code is the one thing this must never do, because the
  shop looks one up and refunds the other.
- **Enumeration.** It is not a credential — holding a code grants nothing — but
  a sequential-looking number invites a support desk to accept it as proof of
  identity, and invites a bored person to walk the range.

So: `BK-` plus six characters of Crockford base32. That alphabet drops I, L, O
and U, which is exactly the set that goes wrong when a distressed client reads
a code to a stylist over a bad line — no I/1 or O/0 confusion, and no accidental
words. Six characters is ~1.07 × 10⁹ codes, generated with `secrets`.

Uniqueness is a database constraint. The pre-check here only keeps the retry
loop short; it is not what makes the code unique.
"""

import secrets

#: Crockford base32. No I, L, O or U — see the module docstring.
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PREFIX = "BK-"
LENGTH = 6

#: Enough attempts that a collision is a bug rather than bad luck. At the
#: densities this product will ever see, the first attempt always wins.
MAX_ATTEMPTS = 8


class CouldNotMintSupportCode(RuntimeError):
    pass


def _mint():
    return PREFIX + "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))


def new_support_code():
    """A code that is not already in use.

    `.unscoped()` because a support code is global by design: the client rings
    the shop, the shop searches, and neither of them knows an organization id.
    """
    from payments.models import Payment

    for _ in range(MAX_ATTEMPTS):
        code = _mint()
        if not Payment.objects.unscoped().filter(support_code=code).exists():
            return code
    raise CouldNotMintSupportCode(
        f"{MAX_ATTEMPTS} attempts collided. That is not luck — check the alphabet and length."
    )
