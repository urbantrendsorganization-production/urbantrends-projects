"""Kenyan phone numbers, normalised to E.164.

Phones are the identifier for everything here: staff log in with one, clients
are reached on one, and M-Pesa pushes to one. The same person will type
`0712 345 678` on one screen and `+254712345678` on another, and both must
resolve to the same row — otherwise a staff member gets locked out of their own
account and a returning client gets a second, empty history.

Kenyan mobile prefixes after the country code are 7xx (Safaricom, Airtel,
Telkom) and 1xx (the newer Safaricom 011x range).
"""

import re

MOBILE = re.compile(r"^[71]\d{8}$")
_STRIP = re.compile(r"[\s\-().]")

COUNTRY_CODE = "254"


class InvalidPhoneNumber(ValueError):
    pass


def normalize_phone(raw):
    """`0712345678` / `254712345678` / `+254 712 345 678` -> `+254712345678`."""
    if raw is None:
        raise InvalidPhoneNumber("A phone number is required")

    digits = _STRIP.sub("", str(raw)).lstrip("+")

    if digits.startswith(COUNTRY_CODE):
        national = digits[len(COUNTRY_CODE) :]
    elif digits.startswith("0"):
        national = digits[1:]
    else:
        national = digits

    if not MOBILE.match(national):
        raise InvalidPhoneNumber(
            f"{raw!r} is not a Kenyan mobile number. Expected a 07xx/01xx number, "
            "with or without the +254 country code."
        )

    return f"+{COUNTRY_CODE}{national}"
