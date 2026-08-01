"""Money.

**Every price and deposit figure the client ever sees comes out of this
module.** There is one function that computes a deposit; the model writes its
result to a column, the serializers read that column, and slice 6 pushes it to
M-Pesa. If a second implementation of this arithmetic appears anywhere, the
client will eventually be shown one number and charged another.

## What is stored

Prices and deposits are **integer whole shillings**. Not floats, and not
integer cents.

Floats are excluded for the usual reason: `0.1 + 0.2` is not `0.3`, and money
that does not add up destroys trust in a product whose entire pitch is
"the deposit is real".

Cents are excluded for a Kenyan reason. The M-Pesa Daraja STK push takes an
integer shilling amount — there is no way to move KES 3,500.50 through it. A
schema that can express a price we cannot charge invites a row that can never
be booked, and forces a rounding step at the payment boundary where it is
least visible. Rounding has to happen somewhere; better at definition time,
once, in this file, than silently inside the payment call. Kenyan salons price
in whole shillings anyway — the design's own examples are KES 3,500 and
KES 1,000.

The cost of this choice: a service cannot be priced at KES 3,500.50. No salon
prices that way, and if one ever needs to, the migration is
`price -> price_cents` with a factor of 100, not a redesign.

## Rounding

Percentage deposits round **half up** to the nearest shilling. 25% of KES 1,333
is 333.25, which becomes KES 333; 25% of KES 1,334 is 333.50, which becomes
KES 334. Half-up rather than banker's rounding because the number is read by a
person comparing it to a percentage in their head, and "round .5 to even" is
not a rule anyone applies mentally.

Decimal, not float, throughout — `0.25 * 1333` in binary floating point is
333.2499999999999886313162278.

Two clamps after rounding:

- **Never zero.** A percentage that rounds down to nothing is not a deposit,
  and a service that takes a KES 0 deposit is a free no-show. Floor of 1.
- **Never more than the price.** A deposit larger than the bill is a refund
  waiting to happen.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db import models

WHOLE_SHILLING = Decimal("1")
PERCENT = Decimal("100")

#: Pre-filled at service creation. CLAUDE.md §12 — the shop sets the rule, but
#: charging nothing has to be a deliberate change rather than the default.
DEFAULT_DEPOSIT_PERCENT = Decimal("25")


class DepositMode(models.TextChoices):
    NONE = "none", "No deposit"
    FLAT = "flat", "Flat amount"
    PERCENT = "percent", "Percentage of price"


def deposit_amount(*, mode, value, price):
    """Whole shillings to take up front. The only implementation of this.

    `value` is shillings when `mode` is flat, and a percentage when `mode` is
    percent. Returns 0 only when no deposit is due at all — a service with
    `mode=none`, or a service priced at zero.
    """
    if mode == DepositMode.NONE or price <= 0 or value is None:
        return 0

    if mode == DepositMode.FLAT:
        amount = Decimal(value)
    elif mode == DepositMode.PERCENT:
        amount = Decimal(price) * Decimal(value) / PERCENT
    else:
        raise ValueError(f"Unknown deposit mode {mode!r}")

    shillings = int(amount.quantize(WHOLE_SHILLING, rounding=ROUND_HALF_UP))

    # A deposit that rounds away to nothing is not a deposit.
    shillings = max(shillings, 1)
    # And one larger than the bill is a refund waiting to happen.
    return min(shillings, price)


def format_kes(shillings):
    """`KES 1,000`. Never `1.5k` — the design is explicit about this."""
    return f"KES {shillings:,}"
