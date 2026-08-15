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

2. **One open hold per phone per stylist** (`MAX_OPEN_HOLDS_PER_STAFF`). This
   is the control that actually bounds the attack, because the attack is
   hoarding *one stylist's* day: doing that still needs one distinct phone
   number per concurrently held slot.

   It is scoped per stylist rather than per organization, and that scoping was
   deliberate. A parent booking two children on one phone — one with Wanjiku,
   one with Grace, at the same time, which is what a Saturday morning at a salon
   actually looks like — is a completely ordinary request that a
   one-hold-per-number ceiling refuses outright. That refusal arrives as "you
   already have a slot held" at the worst possible moment, and the client's only
   remedy is to abandon a booking they wanted.

   The loosening is small and bounded. A number can now hold at most one slot
   per bookable stylist, which is 2–8 on a real shop, and the daily ceiling
   below caps it at 6 regardless. What it does not permit is the thing worth
   preventing: two simultaneous holds on the same stylist.

   Two slots with the *same* stylist on one number is still refused while a
   hold is open. That case resolves itself in slice 6 — an STK push confirms in
   seconds, the first hold leaves `pending_payment`, and the second booking
   proceeds — so it is a sequencing constraint for as long as there is no
   payment, not a permanent one.

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

Scoping control 2 per stylist rather than per number does not move either
figure. The 500-number case was already one number per *slot*, and the
one-stylist case is bounded by the daily ceiling, not by the open-hold ceiling.
What it changes is the honest-client case, which it stops refusing.

## Why per-IP is the weakest control here and is set loose

Safaricom and Airtel put large numbers of Kenyan mobile subscribers behind
carrier-grade NAT. A per-IP limit tight enough to matter would block a
neighbourhood on a Saturday morning. So the IP throttle in settings is set as a
crude ceiling against a single unsophisticated script, and the per-phone limits
above are the real control. Anyone claiming per-IP protects this surface has
not looked at where the traffic comes from.

## The rule that follows from it: one scope per public endpoint

**Every new public endpoint gets its own throttle scope. No exceptions, no
sharing, decided when the endpoint is written and not when it breaks.**

CGNAT makes a shared scope worse than it looks. A shared budget is not "these
endpoints together get 240/hour" — it is "one client's traffic can exhaust the
allowance of every stranger who happens to share their operator's NAT pool",
and the endpoint that gets the 429 is whichever one they touch next, not the
noisy one. The failure surfaces as an unrelated screen freezing for somebody
who did nothing.

This has now cost us twice. Slice 5 set the per-IP hold limit tight enough to
refuse honest clients, which is what the per-phone controls above exist to fix.
Slice 6 put a 3-second poll on `hold-detail` inside `public-read`: ~180 requests
for one booking against a ceiling shared with the shop, service, staff and
availability reads, so two clients behind one NAT address 429'd each other in
the middle of paying — and a 429 there freezes the STK screen on "check your
phone" with money already gone.

Both were the same mistake in a new place. A per-endpoint scope makes the
budget a property of the endpoint's own traffic shape, so a polled endpoint
being polled cannot starve a page nobody is looking at. Scopes are cheap; a
client stuck mid-payment is not.

`core/tests/test_throttle_scopes.py` enforces this — a public view added
without its own scope fails there rather than in production.
"""

from datetime import timedelta

from django.utils import timezone

from scheduling.models import Appointment
from scheduling.statuses import AppointmentStatus, BookingSource

#: Per stylist, not per number. Two unpaid holds on *one* stylist means one was
#: abandoned; two on different stylists means a parent with two children. See
#: control 2 in the module docstring.
MAX_OPEN_HOLDS_PER_STAFF = 1
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


def check_can_hold(client, *, staff=None, now=None):
    """Raise `HoldRefused` if this client may not create another hold.

    Takes the resolved `Client` rather than a raw phone string, so the limits
    are org-scoped exactly as the client record is — the same number at two
    unrelated salons is two people under two controllers (CLAUDE.md §9), and
    one shop's abandoned holds must not lock somebody out of another's.

    `staff` scopes the open-hold ceiling. It is optional only so the daily and
    abandonment limits stay callable without one; every real caller passes it.
    """
    now = now or timezone.now()
    holds = _holds_by(client)

    open_now = holds.filter(status=AppointmentStatus.PENDING_PAYMENT, hold_expires_at__gt=now)
    if staff is not None:
        open_now = open_now.filter(staff=staff)
    if open_now.count() >= MAX_OPEN_HOLDS_PER_STAFF:
        # Named, because "you already have a slot held" with no name reads as a
        # refusal of the whole booking rather than of this one stylist — and the
        # remedy (pick someone else, or finish the other booking) is different.
        who = f" with {staff.display_name}" if staff is not None else ""
        raise HoldRefused(
            f"You already have a slot held{who}. Finish that booking, or cancel it first.",
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
