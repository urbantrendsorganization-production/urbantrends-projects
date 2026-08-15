"""Safaricom's result codes, turned into something a client can read.

The design's screen 7 says the reason is named **verbatim** — "insufficient
funds", not "payment failed". That is right, and it has a limit: not every
`ResultDesc` Safaricom sends is safe to put in front of a client.

    "Merchant does not exist"
    "Invalid Access Token"

are our configuration problems. Showing them to a client turns our outage into
their confusion, and reads as an accusation about their account. So the verbatim
text is **stored** on every payment — `Payment.result_desc`, which is what a
dispute and the admin read — and what the *client* sees comes from this table,
with a safe default for anything unmapped.

The remedy matters as much as the wording. "Insufficient funds" and "you
cancelled it" both need "try again"; "wrong PIN" needs the same; a transaction
already in process needs "wait". They are not the same next move, so they are
not the same sentence.
"""

#: `result_code -> (what the client reads, what to suggest next)`.
#:
#: Codes are Safaricom's, observed on both sandbox and live. Anything not here
#: falls through to `DEFAULT`, which is deliberately vague about cause and
#: precise about consequence.
RESULT_MESSAGES = {
    0: ("Paid.", ""),
    1: (
        "There wasn't enough in the M-Pesa account.",
        "Top up and try again, or use a different number.",
    ),
    1032: (
        "The prompt was cancelled on the phone.",
        "Try again when you're ready.",
    ),
    1037: (
        "The prompt didn't reach the phone in time.",
        "Check the phone is on and has signal, then try again.",
    ),
    1001: (
        "That number already has an M-Pesa transaction in progress.",
        "Wait a moment for it to finish, then try again.",
    ),
    2001: (
        "The M-Pesa PIN was wrong.",
        "Try again — the prompt will come back.",
    ),
    1019: (
        "The transaction expired before it was completed.",
        "Try again.",
    ),
    1025: (
        "M-Pesa couldn't process the request.",
        "Try again in a moment.",
    ),
}

DEFAULT = (
    "M-Pesa didn't complete the payment.",
    "Nothing was taken. Try again, or use a different number.",
)

#: A push Safaricom refused before it ever went out. There is no `ResultCode`
#: here — the rejection came from the push call, not from a callback — so this
#: does not live in `RESULT_MESSAGES`. Without it screen 7 shows a failure with
#: a blank reason, which reads as a bug rather than as something to retry.
PUSH_NOT_SENT = (
    "We couldn't reach M-Pesa to send the prompt.",
    "Nothing was taken. Try again, or dial the fallback below.",
)


def push_not_sent_message():
    """What screen 7 shows when the push was refused before it was sent."""
    return " ".join(PUSH_NOT_SENT)


# The USSD fallback line (CLAUDE.md §10, invariant 4) deliberately does *not*
# live here. It was defined in this module and again in `config/settings`, and
# only the settings one was ever read — two literals for an invariant the §10
# note says must not be editable away is exactly the drift the invariant exists
# to prevent. `settings.USSD_FALLBACK` is the one definition on the Python side;
# `packages/tokens` is the one definition on the client side, and
# `web/scripts/check-invariants.mjs` guards that one in CI.


def client_message(result_code):
    """One sentence, safe to show, plus what to do about it."""
    reason, remedy = RESULT_MESSAGES.get(result_code, DEFAULT)
    return f"{reason} {remedy}".strip()


def is_user_cancelled(result_code):
    """1032 — they pressed cancel. Not a failure to retry with a new number."""
    return result_code == 1032
