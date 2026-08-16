"""Encrypting a credential that has to live in the database.

CLAUDE.md §11 says secrets come from the environment, and until slice 13 they
all did. Per-shop M-Pesa credentials are the exception the rule could not
survive: the SaaS front door in §1 is an owner signing themselves up, and an
onboarding step that requires us to edit an env file and redeploy is not
self-serve. So the passkey and consumer secret move into a column, and this
module is the reason that is not simply worse.

## Why not plaintext

The threat is not somebody with a shell on the box — they have the key too.
It is every way a *copy* of the database leaves the box while the key does not:
a `pg_dump` on a laptop, a backup bucket, a restored staging snapshot, a
read-only replica handed to an analyst, an ORM debug page. Each of those is
routine, and each one in the clear is every shop's live till credentials at
once. Encrypted, a dump is inert.

## Why Fernet, and why a dependency at all

Neither Django nor the stdlib does authenticated symmetric encryption.
`hashlib` and `hmac` verify that something was not tampered with; they do not
conceal it, and `django.core.signing` is the same — signed, readable by anyone
holding the payload. There is no way to do this correctly without either
`cryptography` or hand-rolling AES-GCM against `os.urandom`, and hand-rolling
the one thing in the repo whose failure is silent is the wrong economy. Fernet
is AES-128-CBC with an HMAC, a standard construction with no knobs to get
wrong, and it ships in the same package Django already expects for other
optional features.

## Rotation, because a key you cannot change is a key you cannot lose safely

`MPESA_CREDENTIAL_KEYS` is `id:key` pairs, most recent first:

    MPESA_CREDENTIAL_KEYS=2026a:<urlsafe-b64-32-bytes>,2025a:<older-key>

The first entry encrypts. Every entry can decrypt, so adding a new key at the
front is a rotation nobody has to coordinate with a re-encryption pass — and
`Shop.mpesa_key_id` records which key sealed each row, so the pass that
re-encrypts them later can find them with a `WHERE`. Dropping an old key is
therefore a deliberate act taken once nothing references it, rather than the
thing that quietly bricks the oldest shops on the platform.

## What this module will not do

It will not silently accept a missing key. A deployment with no
`MPESA_CREDENTIAL_KEYS` cannot seal, and `seal` raises rather than storing
something readable — the failure mode where secrets are written in the clear
because configuration was incomplete is the entire thing this exists to
prevent. `config/settings/prod.py` refuses to boot without one, so that raise
is a local-development guard rather than a production path.
"""

import binascii

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class SealingUnavailable(RuntimeError):
    """No usable key. Nothing was encrypted and nothing should be stored."""


class CannotUnseal(RuntimeError):
    """The stored ciphertext will not open with any key we hold.

    Two causes and they need telling apart by whoever reads the log: the key
    that sealed it has been dropped from `MPESA_CREDENTIAL_KEYS`, or the column
    was corrupted. Both mean the shop must re-enter its credentials; neither
    means push anything to Safaricom with a guess.
    """


def _configured():
    """`[(key_id, Fernet)]`, newest first. Parsed on every call, deliberately.

    Reading `settings` rather than caching a module global keeps
    `override_settings` working in tests, which is how the rotation behaviour
    is exercised. Fernet construction is a base64 decode and a slice; this is
    not on the booking hot path — one call per STK push, next to a network
    round trip to Safaricom.
    """
    parsed = []
    for entry in settings.MPESA_CREDENTIAL_KEYS:
        key_id, _, material = entry.partition(":")
        key_id = key_id.strip()
        material = material.strip()
        if not key_id or not material:
            raise SealingUnavailable(
                "MPESA_CREDENTIAL_KEYS entries must be 'id:key' — "
                f"got {entry.split(':')[0][:12]!r} with no key"
            )
        try:
            parsed.append((key_id, Fernet(material)))
        except (ValueError, binascii.Error) as exc:
            # Never the key material itself, and never the exception text —
            # `cryptography` puts the offending value in some of its messages.
            raise SealingUnavailable(
                f"MPESA_CREDENTIAL_KEYS entry {key_id!r} is not a valid Fernet key "
                "(32 url-safe base64-encoded bytes)"
            ) from exc
    if not parsed:
        raise SealingUnavailable(
            "MPESA_CREDENTIAL_KEYS is not set, so a shop's M-Pesa credentials "
            "cannot be encrypted. Generate one with: python -c 'from "
            "cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    return parsed


def sealing_is_available():
    """Can this deployment store a credential at all? For readiness and forms."""
    try:
        _configured()
    except SealingUnavailable:
        return False
    return True


def active_key_id():
    """The id of the key `seal` will use."""
    return _configured()[0][0]


def seal(plaintext):
    """`(ciphertext, key_id)` for a secret about to be written to a column.

    Returns `(b"", "")` for an empty value so "the shop has not set this" stays
    representable without a nullable column and without a ciphertext that
    decrypts to nothing — a sealed empty string would be indistinguishable from
    a set-but-blank passkey to every caller, and one of those should push and
    the other should refuse.
    """
    if not plaintext:
        return b"", ""
    key_id, fernet = _configured()[0]
    return fernet.encrypt(plaintext.encode()), key_id


def unseal(ciphertext, key_id=""):
    """The plaintext, or `""` if nothing was ever stored.

    `key_id` is advisory: every configured key is tried regardless, so a row
    sealed under a key that has since moved down the list still opens. It is
    recorded on the model for the re-encryption pass and for the error message
    here, which is the difference between "rotate your keys back" and "this row
    is corrupt".
    """
    if not ciphertext:
        return ""
    for _, fernet in _configured():
        try:
            return fernet.decrypt(bytes(ciphertext)).decode()
        except InvalidToken:
            continue
    raise CannotUnseal(
        f"no configured key opens a credential sealed under {key_id or 'an unrecorded key'} — "
        "either MPESA_CREDENTIAL_KEYS no longer contains it, or the row is damaged"
    )


def mask(plaintext, *, keep=4):
    """What a credential looks like coming back out of the API.

    Never the value. Enough to answer "is the thing I typed still the thing
    that is stored", which is the only question an owner has about a secret
    they cannot read — and short values are masked entirely rather than
    mostly-revealed, because `keep=4` of a six-character string is not a hint,
    it is the string.
    """
    if not plaintext:
        return ""
    if len(plaintext) <= keep * 2:
        return "•" * 8
    return "•" * 8 + plaintext[-keep:]


def generate_key():
    """A new Fernet key, as the string that goes after the `id:` in the env var."""
    return Fernet.generate_key().decode()
