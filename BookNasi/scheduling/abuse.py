"""The price of the no-OTP decision, written down.

CLAUDE.md §12 locks it: no client account, no OTP, the STK push *is* the phone
verification. That is the right call for conversion — an account step costs
bookings at exactly the point they are most likely to drop — and it has a bill
attached, which this module pays.

## What is actually exposed

An unverified phone number can hold a real slot for `Shop.hold_ttl_minutes`.
Nothing about the number is checked before the hold exists, because checking it
is what the deposit does, and the deposit comes after. So the honest statement
of the exposure is: **anyone who can send an HTTP request can take a stylist's
next slot out of circulation for three minutes, for free.**

What that is *not*: permanent. A hold expires and the slot comes back, so the
worst case is denial of availability while the attack runs, not a corrupted
calendar. Nothing is charged, nothing is confirmed, and no client data is
readable — the hold response returns only what the holder already sent.

## The four controls, and what each costs an attacker

1. **Hold TTL — three minutes** (`Shop.hold_ttl_minutes`, default 3, capped at
   30 by a check constraint). This is the single biggest lever and it is
   already as short as the payment flow tolerates: it has to cover a client
   leaving the page, finding the M-Pesa prompt, and typing a PIN on a phone
   that may also be the one showing the booking page. Shorter would fail honest
   clients; longer multiplies every number below.

2. **One open hold per phone per organization** (`MAX_OPEN_HOLDS_PER_PHONE`).
   The tightest limit that does not break a real client, because a client with
   two unpaid holds is a client who has abandoned one. This is the control that
   actually bounds the attack: filling a stylist's day needs one distinct phone
   number *per concurrently held slot*, not one attacker.

3. **Six holds per phone per day** (`MAX_HOLDS_PER_PHONE_PER_DAY`). Generous
   enough for a client whose first STK push failed, whose second timed out, and
   who then changed their mind about the time. Beyond that a number is not
   booking a haircut.

4. **Abandonment cooldown** — `MAX_ABANDONED_HOLDS` expiries inside
   `ABANDONED_WINDOW` costs that number `ABANDONED_COOLDOWN`. Only *expiries*
   count. A client who cancels their hold is not penalised at all, which is
   deliberate: the alternative teaches people to walk away from the page rather
   than press the cancel button, and walking away is the behaviour that costs
   the shop a slot.

Plus the booking horizon from slice 3 (`Shop.booking_horizon_days`, default 60),
which is why an unbounded horizon was rejected there: it is what stops one
number from being pointed at a stylist's entire year.

## The arithmetic, so it is priced rather than assumed

A shop with eight stylists and a nine-hour day has roughly 500 offerable starts
across a 60-day horizon at any one moment. Holding all of them simultaneously
needs ~500 distinct phone numbers, each re-issuing every three minutes, for as
long as the attack is to last. That is a real cost in SIM cards and it is
observable — 500 numbers each creating one hold and never paying is not a shape
that occurs naturally, and slice 6's payment records make it trivially
reportable.

Holding *one stylist's next slot* continuously, which is the cheap and more
likely nuisance, needs one number and 20 requests an hour. That is inside the
per-day limit for the first six and then blocked, so it costs six numbers a day.
This is the residual risk and it is accepted rather than solved: solving it
means an OTP, and CLAUDE.md §12 priced that trade already.

## Why per-IP is the weakest control here and is set loose

Safaricom and Airtel put large numbers of Kenyan mobile subscribers behind
carrier-grade NAT. A per-IP limit tight enough to matter would block a
neighbourhood on a Saturday morning. So the IP throttle in settings is set as a
crude ceiling against a single unsophisticated script, and the per-phone limits
above are the real control. Anyone claiming per-IP protects this surface has
not looked at where the traffic comes from.
"""

from datetime import timedelta

from django.utils import timezone

from scheduling.models import Appointment
from scheduling.statuses import AppointmentStatus, BookingSource

#: A client with two unpaid holds has abandoned one.
MAX_OPEN_HOLDS_PER_PHONE = 1
#: Failed push, timed out push, changed their mind — with room to spare.
MAX_HOLDS_PER_PHONE_PER_DAY = 6

#: Expiries only. Cancelling is free; walking away is not.
MAX_ABANDONED_HOLDS = 3
ABANDONED_WINDOW = timedelta(hours=1)
ABANDONED_COOLDOWN = timedelta(minutes=30)


class HoldRefused(Exception):
    """This number may not take another hold right now.

    Distinct from `SlotUnavailable` and `SlotTaken`: the slot is fine, the
    caller is the problem. Carries `retry_after` in seconds so the response can
    say when rather than just no — a client who has genuinely abandoned two
    holds and is trying a third is usually a real person having a bad time on a
    bad connection, and "try again in 12 minutes" is a better answer than a
    blank refusal.
    """

    def __init__(self, message, *, retry_after=None, reason=""):
        self.retry_after = retry_after
        self.reason = reason
        super().__init__(message)


def _holds_by(client):
    return Appointment.objects.for_org(client.organization_id).filter(
        client=client, source=BookingSource.ONLINE
    )


def check_can_hold(client, *, now=None):
    """Raise `HoldRefused` if this client may not create another hold.

    Takes the resolved `Client` rather than a raw phone string, so the limits
    are org-scoped exactly as the client record is — the same number at two
    unrelated salons is two people under two controllers (CLAUDE.md §9), and
    one shop's abandoned holds must not lock somebody out of another's.
    """
    now = now or timezone.now()
    holds = _holds_by(client)

    open_now = holds.filter(
        status=AppointmentStatus.PENDING_PAYMENT, hold_expires_at__gt=now
    ).count()
    if open_now >= MAX_OPEN_HOLDS_PER_PHONE:
        raise HoldRefused(
            "You already have a slot held. Finish that booking, or cancel it first.",
            reason="open_hold",
        )

    today = holds.filter(created_at__gte=now - timedelta(days=1)).count()
    if today >= MAX_HOLDS_PER_PHONE_PER_DAY:
        raise HoldRefused(
            "That number has held too many slots today. Try again tomorrow, or call the shop.",
            retry_after=int(timedelta(days=1).total_seconds()),
            reason="daily_limit",
        )

    abandoned = holds.filter(hold_released_at__gte=now - ABANDONED_WINDOW).order_by(
        "-hold_released_at"
    )[:MAX_ABANDONED_HOLDS]
    abandoned = list(abandoned)
    if len(abandoned) >= MAX_ABANDONED_HOLDS:
        # From the *oldest* of the three, so the cooldown shortens as they age
        # out rather than restarting on every attempt. A cooldown that resets
        # when you retry is a permanent ban with extra steps.
        until = abandoned[-1].hold_released_at + ABANDONED_COOLDOWN
        if until > now:
            raise HoldRefused(
                "That number has let several held slots expire. "
                f"Try again in {max(1, int((until - now).total_seconds() // 60))} minutes.",
                retry_after=int((until - now).total_seconds()),
                reason="abandonment_cooldown",
            )
