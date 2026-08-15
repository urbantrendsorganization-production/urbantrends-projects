"""Safaricom Daraja, behind one small interface.

Two operations, and they are not symmetric:

- `push` asks Safaricom to put a PIN prompt on a phone. It answers immediately
  with an id and tells us nothing about whether anyone paid.
- `query` asks what became of a push. **This is not a fallback for a missing
  callback — it is the other half of the design.** Without it, "no callback"
  and "no payment" are the same observation, and we release a slot somebody
  paid for and never find out. See `payments/tasks.py`.

## No HTTP dependency

`urllib.request` and `json`. CLAUDE.md §11: no dependency for what the stdlib
already does, and this is a POST with a bearer token.

## Nothing real in the repo

Credentials come from the environment (CLAUDE.md §5, §11). `.env.example`
carries the names and no values, sandbox included — a sandbox shortcode is
still a credential and still identifies an account.

## What is never logged

Not the request body: it contains the payer's number and the password hash.
Not the response body: the sandbox echoes the number back. Ids and result codes
only, which is enough to trace anything with.
"""

import base64
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class DarajaUnavailable(Exception):
    """The request did not complete, and we do not know whether it landed.

    Deliberately distinct from a rejection. A rejection means no money will
    move; this means we cannot tell, which is the case that has to become
    `UNKNOWN` and be queried rather than assumed away.
    """


#: The two STK transaction types. Mirrored from `config.settings.base` rather
#: than imported, so this module stays importable without Django settings for
#: the same reason the rest of it avoids them where it can.
PAYBILL = "CustomerPayBillOnline"
TILL = "CustomerBuyGoodsOnline"


class DarajaMisconfigured(Exception):
    """Our configuration is wrong, not Safaricom's answer.

    Deliberately **not** a `DarajaUnavailable`: that one means "we cannot tell
    whether the prompt went out" and is retried by the reconciliation query.
    This means no push was attempted and none should be, because attempting it
    would send a client's deposit somewhere the shop is not looking. Retrying it
    on a schedule would just be wrong on a schedule.
    """


class DarajaRejected(Exception):
    """Safaricom answered and said no. No prompt was sent, no money will move."""

    def __init__(self, message, *, code=""):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class PushAccepted:
    merchant_request_id: str
    checkout_request_id: str
    customer_message: str = ""


@dataclass(frozen=True)
class QueryResult:
    """What `query` found.

    `result_code is None` means Safaricom answered but the transaction is still
    in flight — its own "being processed" error. That is a real answer and it
    is not a failure: it means try again later, not give up.
    """

    result_code: int | None
    result_desc: str = ""


#: Kenya is UTC+3 and does not observe DST. CLAUDE.md §4 forbids a timezone
#: abstraction layer for exactly this reason, which is what makes a constant
#: offset safe here rather than a landmine.
EAT_OFFSET = timedelta(hours=3)


def _timestamp(now=None):
    """Daraja's `Timestamp`: the shortcode's local wall clock, `YYYYMMDDHHMMSS`."""
    now = now or datetime.now(tz=UTC)
    return (now + EAT_OFFSET).strftime("%Y%m%d%H%M%S")


def _password(shortcode, passkey, stamp):
    return base64.b64encode(f"{shortcode}{passkey}{stamp}".encode()).decode()


class DarajaClient:
    """The real one. Used in production; never instantiated by a test."""

    def __init__(self, config=None):
        self.config = config or settings.MPESA
        self._token = None
        self._token_expires = 0.0

    # ------------------------------------------------------- paybill or till

    @property
    def transaction_type(self):
        """`CustomerPayBillOnline` or `CustomerBuyGoodsOnline`.

        Validated here rather than trusted, because the value goes straight into
        the push body and a third string is a rejection from Safaricom carrying
        an error code the client never sees the inside of.
        """
        configured = (self.config.get("TRANSACTION_TYPE") or PAYBILL).strip()
        if configured not in (PAYBILL, TILL):
            raise DarajaMisconfigured(
                f"MPESA_TRANSACTION_TYPE must be {PAYBILL} or {TILL}, got {configured!r}"
            )
        return configured

    @property
    def party_b(self):
        """Whose account the money lands in.

        For a till this is the till number and **not** `BusinessShortCode`.
        Sending the store number as `PartyB` on a BuyGoods push is the failure
        worth being loud about: Safaricom may well accept it, the client's PIN
        prompt appears, the money moves, and it does not arrive where the shop
        is looking for it. A missing till number is therefore a refusal to push
        rather than a fallback to the shortcode.
        """
        if self.transaction_type == PAYBILL:
            return self.config["SHORTCODE"]
        till = (self.config.get("TILL_NUMBER") or "").strip()
        if not till:
            raise DarajaMisconfigured(
                f"MPESA_TILL_NUMBER is required when MPESA_TRANSACTION_TYPE is {TILL}"
            )
        return till

    # ---------------------------------------------------------------- http

    def _post(self, path, body, *, headers=None):
        url = f"{self.config['BASE_URL'].rstrip('/')}{path}"
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config["TIMEOUT_SECONDS"]) as reply:
                return json.loads(reply.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            # A 4xx from Daraja is an answer: it carries errorCode/errorMessage
            # and means the push was refused. A 5xx is not an answer.
            raw = exc.read().decode() or "{}"
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = {}
            if 400 <= exc.code < 500:
                raise DarajaRejected(
                    parsed.get("errorMessage", "Safaricom refused the request"),
                    code=str(parsed.get("errorCode", exc.code)),
                ) from exc
            raise DarajaUnavailable(f"Daraja returned {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Socket timeout, DNS, connection reset. We do not know whether the
            # push went out. This is the case `UNKNOWN` exists for.
            raise DarajaUnavailable(str(exc)) from exc

    def _access_token(self):
        if self._token and time.monotonic() < self._token_expires:
            return self._token
        credentials = base64.b64encode(
            f"{self.config['CONSUMER_KEY']}:{self.config['CONSUMER_SECRET']}".encode()
        ).decode()
        url = (
            f"{self.config['BASE_URL'].rstrip('/')}/oauth/v1/generate?grant_type=client_credentials"
        )
        request = urllib.request.Request(url, headers={"Authorization": f"Basic {credentials}"})
        try:
            with urllib.request.urlopen(request, timeout=self.config["TIMEOUT_SECONDS"]) as reply:
                payload = json.loads(reply.read().decode())
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise DarajaUnavailable(f"could not obtain an access token: {exc}") from exc
        self._token = payload["access_token"]
        # Daraja issues an hour; expire early so a token never dies mid-push.
        self._token_expires = time.monotonic() + int(payload.get("expires_in", 3599)) - 120
        return self._token

    def _auth(self):
        return {"Authorization": f"Bearer {self._access_token()}"}

    # ------------------------------------------------------------ the two

    def push(self, *, amount, phone, reference, description):
        stamp = _timestamp()
        shortcode = self.config["SHORTCODE"]
        msisdn = phone.lstrip("+")
        body = {
            # Always the store / head office number, in both modes, because it
            # is what the password is derived from. For a till this is *not* the
            # till number.
            "BusinessShortCode": shortcode,
            "Password": _password(shortcode, self.config["PASSKEY"], stamp),
            "Timestamp": stamp,
            "TransactionType": self.transaction_type,
            "Amount": int(amount),
            "PartyA": msisdn,
            # The one field that differs between the two modes, and the one that
            # decides whose account the deposit lands in. Paybill: the paybill
            # number. Till: the till number, which is a different number from
            # `BusinessShortCode` above.
            "PartyB": self.party_b,
            "PhoneNumber": msisdn,
            "CallBackURL": self.config["CALLBACK_URL"],
            # Daraja truncates both silently. Doing it here means the reference
            # we send is the reference we stored, not a prefix of it.
            "AccountReference": reference[:12],
            "TransactionDesc": description[:60],
        }
        payload = self._post("/mpesa/stkpush/v1/processrequest", body, headers=self._auth())
        if str(payload.get("ResponseCode", "")) != "0":
            raise DarajaRejected(
                payload.get("ResponseDescription", "Safaricom refused the push"),
                code=str(payload.get("ResponseCode", "")),
            )
        # `.get`, like every other field on this response. A 200 with
        # `ResponseCode: 0` and no CheckoutRequestID would otherwise raise a
        # KeyError, which is neither `DarajaRejected` nor `DarajaUnavailable`,
        # so it would escape `_send`, escape `initiate_push` and escape the
        # `except PushRefused` in the hold view — a 500 for a hold that was
        # created and is now sitting on the slot with no way to pay for it.
        # Unavailable rather than rejected: Safaricom said yes, we simply have
        # no id to reconcile with, so the prompt may well be on the phone.
        checkout_request_id = payload.get("CheckoutRequestID") or ""
        if not checkout_request_id:
            raise DarajaUnavailable("Safaricom accepted the push but returned no CheckoutRequestID")
        return PushAccepted(
            merchant_request_id=payload.get("MerchantRequestID", ""),
            checkout_request_id=checkout_request_id,
            customer_message=payload.get("CustomerMessage", ""),
        )

    def query(self, checkout_request_id):
        stamp = _timestamp()
        shortcode = self.config["SHORTCODE"]
        body = {
            "BusinessShortCode": shortcode,
            "Password": _password(shortcode, self.config["PASSKEY"], stamp),
            "Timestamp": stamp,
            "CheckoutRequestID": checkout_request_id,
        }
        try:
            payload = self._post("/mpesa/stkpushquery/v1/query", body, headers=self._auth())
        except DarajaRejected as exc:
            # 500.001.1001 is Daraja's "the transaction is being processed".
            # It arrives as a 4xx and it is not a refusal — it means ask again.
            if exc.code == "500.001.1001":
                return QueryResult(result_code=None, result_desc="still processing")
            raise
        code = payload.get("ResultCode")
        return QueryResult(
            result_code=int(code) if code is not None and str(code) != "" else None,
            result_desc=payload.get("ResultDesc", ""),
        )


@dataclass
class FakeDarajaClient:
    """What local development and every test runs against.

    Not a mock library and not a monkeypatch: a real implementation of the same
    two methods, selected by `settings.MPESA_CLIENT`, whose behaviour a test
    sets by assignment. That keeps the seam at the interface rather than inside
    the code under test, so `stk.py` and `callbacks.py` are exercised exactly as
    they run in production.
    """

    pushes: list = field(default_factory=list)
    queries: list = field(default_factory=list)
    #: Set to a `DarajaUnavailable` or `DarajaRejected` to make the next push
    #: behave that way. The two are very different states and both need testing.
    push_error: Exception | None = None
    query_error: Exception | None = None
    next_query_result: QueryResult | None = None
    _counter: int = 0

    def push(self, *, amount, phone, reference, description):
        self.pushes.append(
            {"amount": amount, "phone": phone, "reference": reference, "desc": description}
        )
        if self.push_error is not None:
            error, self.push_error = self.push_error, None
            raise error
        self._counter += 1
        return PushAccepted(
            merchant_request_id=f"MRQ-{self._counter}",
            checkout_request_id=f"ws_CO_fake_{self._counter}",
            customer_message="Success. Request accepted for processing",
        )

    def query(self, checkout_request_id):
        self.queries.append(checkout_request_id)
        if self.query_error is not None:
            error, self.query_error = self.query_error, None
            raise error
        if self.next_query_result is not None:
            result, self.next_query_result = self.next_query_result, None
            return result
        return QueryResult(result_code=None, result_desc="still processing")


_client = None


def get_client():
    """The process-wide client.

    Cached because `DarajaClient` holds an access token worth reusing — minting
    one per push doubles every round trip on a connection where that is the
    whole latency budget.
    """
    global _client
    if _client is None:
        _client = import_string(settings.MPESA_CLIENT)()
    return _client


def reset_client():
    """Drop the cached client. For tests, and for a settings override."""
    global _client
    _client = None
