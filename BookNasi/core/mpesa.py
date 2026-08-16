"""The two Daraja transaction types, and what a shortcode may look like.

Here rather than in `payments/` because after slice 13 three places need them
and the dependency arrows do not all point the same way: `config/settings`
loads before any app, `shops/models.py` puts them in a field's `choices`, and
`payments/daraja.py` deliberately avoids importing Django settings so it stays
importable on its own. A module with no models and no settings access is the
only shape all three can reach.

`payments/daraja.py` used to carry its own copy with a comment admitting it was
a mirror. Two copies of a string that goes straight into a request body is a
typo waiting to become a rejection from Safaricom carrying an error code nobody
reads; three would have been worse.
"""

import re

from django.core.exceptions import ValidationError

#: Paybill. `PartyB` is the paybill number itself.
PAYBILL = "CustomerPayBillOnline"
#: Buy Goods. `PartyB` is the **till** number, which is not `BusinessShortCode`.
TILL = "CustomerBuyGoodsOnline"

TRANSACTION_TYPES = (PAYBILL, TILL)

#: Safaricom issues 5–7 digits today. The bound is loose on purpose — a
#: too-tight rule here is a shop that cannot onboard because Safaricom changed
#: something, which is worse than a shop that mistypes and finds out at the
#: first push. What it does refuse is the mistake that is otherwise silent:
#: spaces, dashes and a leading `+`, any of which changes the derived password
#: and produces an authentication failure nobody would connect to a stray
#: character in a form field.
SHORTCODE = re.compile(r"\A[0-9]{4,9}\Z")


def validate_shortcode(value):
    if value and not SHORTCODE.fullmatch(value):
        raise ValidationError(
            "A paybill or till number is 4 to 9 digits, with no spaces or dashes.",
            code="invalid_shortcode",
        )
