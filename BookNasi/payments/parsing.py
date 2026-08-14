"""Reading an STK callback body, and redacting it before it touches disk.

Safaricom sends:

    {"Body": {"stkCallback": {
        "MerchantRequestID": "...", "CheckoutRequestID": "...",
        "ResultCode": 0, "ResultDesc": "...",
        "CallbackMetadata": {"Item": [
            {"Name": "Amount", "Value": 1000},
            {"Name": "MpesaReceiptNumber", "Value": "SJ42K19XQ"},
            {"Name": "TransactionDate", "Value": 20260803113045},
            {"Name": "PhoneNumber", "Value": 254712345678}]}}}}

A failure carries the same envelope with a non-zero `ResultCode` and **no**
`CallbackMetadata` at all, which is why every read here is defensive: the
handler must never raise, because an exception escaping it is a non-200 and a
non-200 is a Safaricom retry.

## Redaction

`PhoneNumber` is stripped before the body is stored. CLAUDE.md §5 is about not
logging payloads at INFO; a database column is worse than a log line, because
it is durable and it is joined to a name. The number we need is already on
`Payment.phone`, put there by the push, so the raw copy buys nothing and costs
a standing DPA liability.
"""

from datetime import UTC, datetime, timedelta

#: Keys whose values never reach storage. Matched case-insensitively because
#: Safaricom's own casing has not been perfectly stable across API versions.
REDACTED_ITEM_NAMES = {"phonenumber", "msisdn"}
REDACTED = "[redacted]"

#: Kenya is UTC+3, no DST — see `payments/daraja.py`.
EAT_OFFSET = timedelta(hours=3)


class MalformedCallback(ValueError):
    """The body is not an STK callback. Recorded, never processed."""


class StkCallback:
    """One parsed callback. A plain object, not a dataclass, because two of its
    fields are derived from a list that may be absent."""

    def __init__(
        self, *, merchant_request_id, checkout_request_id, result_code, result_desc, items
    ):
        self.merchant_request_id = merchant_request_id
        self.checkout_request_id = checkout_request_id
        self.result_code = result_code
        self.result_desc = result_desc
        self.items = items

    @property
    def succeeded(self):
        return self.result_code == 0

    @property
    def receipt(self):
        return str(self.items.get("MpesaReceiptNumber", "") or "")

    @property
    def amount(self):
        raw = self.items.get("Amount")
        try:
            # Safaricom sends 1000 or 1000.0 depending on the channel. Whole
            # shillings everywhere else in this codebase (shops/money.py), so
            # it lands as an int here rather than drifting into Decimal.
            return int(float(raw))
        except (TypeError, ValueError):
            return None

    @property
    def paid_at(self):
        """`TransactionDate` is EAT wall clock as an integer, `20260803113045`."""
        raw = self.items.get("TransactionDate")
        if raw is None:
            return None
        try:
            local = datetime.strptime(str(int(raw)), "%Y%m%d%H%M%S")
        except (TypeError, ValueError):
            return None
        return (local - EAT_OFFSET).replace(tzinfo=UTC)


def parse_callback(body):
    """Turn a callback body into a `StkCallback`, or raise `MalformedCallback`."""
    if not isinstance(body, dict):
        raise MalformedCallback("body is not an object")
    stk = (body.get("Body") or {}).get("stkCallback")
    if not isinstance(stk, dict):
        raise MalformedCallback("no Body.stkCallback")

    checkout = stk.get("CheckoutRequestID")
    if not checkout:
        # Without this there is nothing to be idempotent *on*, which makes the
        # body unusable rather than merely unusual.
        raise MalformedCallback("no CheckoutRequestID")

    raw_code = stk.get("ResultCode")
    try:
        result_code = int(raw_code)
    except (TypeError, ValueError) as exc:
        raise MalformedCallback(f"ResultCode {raw_code!r} is not a number") from exc

    items = {}
    for item in (stk.get("CallbackMetadata") or {}).get("Item") or []:
        if isinstance(item, dict) and "Name" in item:
            items[item["Name"]] = item.get("Value")

    return StkCallback(
        merchant_request_id=str(stk.get("MerchantRequestID", "") or ""),
        checkout_request_id=str(checkout),
        result_code=result_code,
        result_desc=str(stk.get("ResultDesc", "") or "")[:255],
        items=items,
    )


def redact(body):
    """A copy of the body with the payer's number removed.

    Recursive, because the number appears inside `CallbackMetadata.Item` and
    Safaricom has moved fields between envelope versions before. Redacting by
    key name at every depth costs nothing and does not have to be revisited the
    next time the shape changes.
    """
    if isinstance(body, dict):
        out = {}
        for key, value in body.items():
            if isinstance(key, str) and key.lower() in REDACTED_ITEM_NAMES:
                out[key] = REDACTED
            elif (
                isinstance(key, str)
                and key == "Value"
                and str(body.get("Name", "")).lower() in REDACTED_ITEM_NAMES
            ):
                out[key] = REDACTED
            else:
                out[key] = redact(value)
        return out
    if isinstance(body, list):
        return [redact(item) for item in body]
    return body
