"""Shop credit: what a late cancellation leaves behind.

CLAUDE.md §12's refund policy, settled 14 August 2026:

    cancel earlier than the window -> refunded
    cancel later than it           -> **credit at that shop**, for
                                      `deposit_credit_days`, against any service
    no-show                        -> forfeited
    the shop cancels               -> refunded

This module is the third line. Credit is the reason a late cancellation is not a
forfeit, and the reason a client who already knows they will miss an appointment
has something to gain by saying so — a slot nobody frees is worth less to the
shop than a slot freed late, and a forfeit buys silence.

## Where the balance lives, and why it is not one number

**Per issuance, not per client.** Each late cancel writes its own `Credit` row
with its own `expires_at`, taken from that shop's `deposit_credit_days` at the
moment it is issued. A single mutable balance per client cannot express two
credits expiring on different days, and rolling them into one either extends the
earlier expiry — giving away money the policy did not promise — or shortens the
later one, which takes away money it did.

Redemption therefore walks rows, oldest-expiring first, and each row carries its
own `remaining`. That ordering is not arbitrary: spending the credit that dies
soonest is what the client would choose, and doing anything else quietly
forfeits value while a usable balance sits next to it.

## More or less than the new deposit

**More:** partial redemption. The remainder stays on the same row with its
**original** expiry, never extended. Extending it on every use would turn a
60-day credit into a perpetual one for any client willing to make small bookings,
which is a different product from the one §12 describes.

**Less:** the difference goes to M-Pesa as an ordinary STK push. Credit reduces
a deposit; it does not replace the payment mechanism.

**Exactly:** no push at all — and that is the case CLAUDE.md §5's carve-out
exists for. A booking with no STK push would otherwise be an unverified number
holding a slot, which is precisely what the deposit rule forbids. It is not one
here: this credit descends from a succeeded payment made from this number, and a
succeeded payment *is* the phone verification the rule exists to provide. See
§5, where that is written down rather than buried in this docstring.

## Expiry

The credit lapses and the money stays with the shop. That is what §12 promises
and it is only defensible because the client is told: the expiry date goes in
the cancellation SMS that issues it, and it is on the manage page every time
they open it. A sweep marks lapsed rows so the exception queue and slice 9's
reporting can see them; nothing is refunded on expiry.
"""

import secrets
from datetime import timedelta

from django.db import models, transaction
from django.utils import timezone

from core.models import OrgDerivedModel


class CreditState(models.TextChoices):
    """Derived from `remaining` and `expires_at` in every case but one.

    `CANCELLED` is the exception and the reason this is a column rather than a
    property: a shop voiding a credit by hand is a decision somebody made, not a
    fact about the numbers, and it has to survive a later change to either.
    """

    OPEN = "open", "Open"
    SPENT = "spent", "Fully redeemed"
    EXPIRED = "expired", "Expired unused"
    CANCELLED = "cancelled", "Voided by the shop"


#: How a credit came to exist. One value today; named rather than implied
#: because slice 9 reports on it and "why does this shop owe KES 40,000 in
#: credit" is a question with more than one possible answer.
class CreditSource(models.TextChoices):
    LATE_CANCELLATION = "late_cancellation", "Cancelled inside the refund window"
    SHOP_GOODWILL = "shop_goodwill", "Issued by the shop"
    #: Slice 11. A booking whose deposit was paid *with* credit, cancelled early
    #: enough that §12 says the deposit comes back. Money returns in the form it
    #: arrived, so this returns as credit rather than as cash — see `restore`.
    BOOKING_REFUNDED = "booking_refunded", "Returned when a credit-paid booking was cancelled"


class Credit(OrgDerivedModel):
    """One issuance. Scoped to a client and a shop, never to a service.

    §12: "any service at that shop". Scoping it tighter would mean a client
    whose stylist has left cannot spend money they are already owed.

    Not scoped to the organization either, despite being org-derived: a chain
    with two branches has two sets of books, and credit earned by cancelling at
    Kilimani is not the Thika Road branch's liability.
    """

    org_source = "shop"

    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="credits")
    client = models.ForeignKey("clients.Client", on_delete=models.PROTECT, related_name="credits")

    #: Whole shillings, like every other money column here.
    amount_kes = models.PositiveIntegerField()
    #: What is left. Decremented under a row lock — see `redeem`.
    remaining_kes = models.PositiveIntegerField()

    state = models.CharField(max_length=16, choices=CreditState.choices, default=CreditState.OPEN)
    source = models.CharField(
        max_length=24, choices=CreditSource.choices, default=CreditSource.LATE_CANCELLATION
    )

    #: The payment this descends from. PROTECT, not CASCADE: it is the evidence
    #: that the money was real, and it is what CLAUDE.md §5's carve-out relies on
    #: to treat a credit-covered booking as a verified one.
    source_payment = models.ForeignKey(
        "payments.Payment",
        on_delete=models.PROTECT,
        related_name="credits_issued",
        null=True,
        blank=True,
    )
    #: The booking whose cancellation issued it. Kept for the client's own
    #: "where did this come from" line on the manage page.
    source_appointment = models.ForeignKey(
        "scheduling.Appointment",
        on_delete=models.PROTECT,
        related_name="credits_issued",
        null=True,
        blank=True,
    )

    expires_at = models.DateTimeField()
    #: A short human-quotable handle, like `Payment.support_code`. A client
    #: ringing a shop about credit needs something to say that is not a UUID.
    reference = models.CharField(max_length=16, unique=True)

    class Meta:
        db_table = "credits"
        ordering = ["expires_at", "created_at"]
        indexes = [
            # The redemption lookup: this client, this shop, still spendable.
            models.Index(fields=["client", "shop", "state"], name="credit_client_shop_idx"),
            # The expiry sweep.
            models.Index(fields=["state", "expires_at"], name="credit_expiry_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(remaining_kes__lte=models.F("amount_kes")),
                name="credit_remaining_within_amount",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_kes__gte=1), name="credit_amount_positive"
            ),
            # A spent credit has nothing left; an open one does. Belt and
            # braces against a redemption path that forgets to close the row.
            models.CheckConstraint(
                condition=~models.Q(state=CreditState.SPENT) | models.Q(remaining_kes=0),
                name="credit_spent_is_empty",
            ),
        ]

    def __str__(self):
        return f"{self.reference} · KES {self.remaining_kes}/{self.amount_kes}"

    @property
    def is_spendable(self):
        """Open, unexpired and non-empty, by this row's own numbers.

        Deliberately not a `state == OPEN` check: the sweep that flips lapsed
        rows to EXPIRED runs on a schedule, so between a credit expiring and the
        sweep noticing there is a window in which the column is stale and the
        timestamp is not. Reading the timestamp means that window cannot spend
        money the policy says is gone.
        """
        return (
            self.state == CreditState.OPEN
            and self.remaining_kes > 0
            and self.expires_at > timezone.now()
        )


class CreditRedemption(OrgDerivedModel):
    """One application of credit to one booking. Append-only.

    Separate from decrementing `remaining_kes` because the decrement is a number
    and this is the story: which booking, how much, when. A client disputing a
    balance and a shop reconciling its month both need the second one, and a
    running total cannot be reconstructed from a column that has been written
    over four times.
    """

    org_source = "credit"

    credit = models.ForeignKey(Credit, on_delete=models.PROTECT, related_name="redemptions")
    appointment = models.ForeignKey(
        "scheduling.Appointment", on_delete=models.PROTECT, related_name="credit_redemptions"
    )
    amount_kes = models.PositiveIntegerField()

    class Meta:
        db_table = "credit_redemptions"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount_kes__gte=1), name="redemption_amount_positive"
            ),
            # One redemption per credit per booking. A retried request must not
            # spend the same credit twice against the same appointment — the
            # same reasoning as `one_appointment_per_client_request`.
            models.UniqueConstraint(
                fields=["credit", "appointment"], name="one_redemption_per_credit_per_appointment"
            ),
        ]

    def __str__(self):
        return f"{self.credit.reference} → {self.appointment_id}: KES {self.amount_kes}"


# ---------------------------------------------------------------- minting

#: No I, O, 0 or 1. A client reads this down a phone to a shop that types it
#: back, and those four are the pairs that get transcribed wrongly. Same
#: alphabet as `payments/support_codes.py`, for the same reason.
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def mint_reference():
    return "CR-" + "".join(secrets.choice(ALPHABET) for _ in range(6))


def _unique_reference():
    for _ in range(5):  # reference collisions are vanishingly rare; retry anyway
        reference = mint_reference()
        if not Credit.objects.unscoped().filter(reference=reference).exists():
            return reference
    raise RuntimeError("could not mint a unique credit reference")  # pragma: no cover


def issue(*, appointment, payment, amount_kes, now=None, source=CreditSource.LATE_CANCELLATION):
    """Create a credit for a late cancellation. Returns the `Credit`.

    `expires_at` is taken from the shop's `deposit_credit_days` **now**, not
    resolved later: a shop that shortens its window next month must not shorten
    a credit it has already promised, and §12's sentence was shown to this
    client with today's number in it.
    """
    now = now or timezone.now()
    shop = appointment.shop
    reference = _unique_reference()

    return Credit.objects.create(
        shop=shop,
        client=appointment.client,
        amount_kes=amount_kes,
        remaining_kes=amount_kes,
        source=source,
        source_payment=payment,
        source_appointment=appointment,
        expires_at=now + timedelta(days=shop.deposit_credit_days),
        reference=reference,
    )


# -------------------------------------------------------------- redemption


def spendable_for(client, shop, *, now=None):
    """Every credit this client can still spend at this shop, soonest first."""
    now = now or timezone.now()
    return (
        Credit.objects.unscoped()
        .filter(
            client=client,
            shop=shop,
            state=CreditState.OPEN,
            remaining_kes__gt=0,
            expires_at__gt=now,
        )
        .order_by("expires_at", "created_at")
    )


def balance_for(client, shop, *, now=None):
    """What the manage page and the confirm screen show. Never a stale column."""
    if client is None:
        return 0
    total = spendable_for(client, shop, now=now).aggregate(total=models.Sum("remaining_kes"))
    return total["total"] or 0


@transaction.atomic
def redeem(*, client, shop, appointment, amount_kes, now=None):
    """Spend up to `amount_kes` of credit against one booking.

    Returns the total applied, which may be less than asked for and may be zero.
    The caller decides what to do about the shortfall — for a booking that means
    pushing the difference to M-Pesa.

    Rows are locked in expiry order. Two tabs confirming two bookings against one
    credit is the same race as two clients confirming one slot, and it has the
    same answer: the database decides, not an application-level balance read.
    """
    now = now or timezone.now()
    if client is None or amount_kes < 1:
        return 0

    outstanding = amount_kes
    applied = 0
    rows = (
        spendable_for(client, shop, now=now)
        .select_for_update()
        # Re-read inside the lock. A balance computed before it is worthless.
        .all()
    )
    for credit in rows:
        if outstanding < 1:
            break
        take = min(credit.remaining_kes, outstanding)
        if take < 1:
            continue
        credit.remaining_kes -= take
        # SPENT rather than left at zero: the constraint above requires it, and
        # the exception queue reads state rather than doing arithmetic.
        if credit.remaining_kes == 0:
            credit.state = CreditState.SPENT
        credit.save(update_fields=["remaining_kes", "state", "updated_at"])
        CreditRedemption.objects.create(credit=credit, appointment=appointment, amount_kes=take)
        applied += take
        outstanding -= take

    return applied


def restore(*, appointment, now=None):
    """Give back credit spent on a booking §12 says is refundable. Returns the
    new `Credit` rows, newest issuance per source credit, usually one.

    Slice 11 found the gap: `lifecycle.cancel` recorded a refund by stamping
    `Payment.refund_due_at`, and a booking whose deposit came from credit has no
    `Payment` row of its own, so the `.update()` matched nothing. The client was
    told on screen and by SMS that the shop would refund them, the shop's
    "Refund owed to the client" queue stayed empty, and the credit stayed spent.
    The money simply left.

    ## Why credit and not cash

    §12's table says "refunded", and the honest reading of that for money that
    arrived as credit is that it goes back as credit — **money returns in the
    form it arrived**. Paying it out as cash would turn credit into a cash
    withdrawal: a credit exists because a *late* cancellation forfeits nothing
    but keeps the money at the shop, and a client who could book and cancel
    early would convert it to cash at will. A mixed deposit splits the same way,
    each half returning whence it came, and the cash half is still stamped for
    the exception queue by the caller.

    ## Why a new row rather than putting the number back

    `CreditRedemption` is append-only on purpose — it is the story of which
    booking spent what. Incrementing the source credit's `remaining_kes` would
    leave the spend recorded and the return not, so the row would disagree with
    the sum of its own redemptions. A fresh issuance keeps both halves visible
    and gives the client a reference to quote.

    ## The expiry is the source credit's, not a new window

    Decided with the policy: a restored credit keeps the expiry of the credit it
    came from. Minting a fresh `deposit_credit_days` here would make booking and
    cancelling an unbounded extension — spend it, cancel, get it back for
    another sixty days, forever. One credit per source redemption rather than
    one lump, so a deposit drawn from two credits with different expiries gives
    each portion its own date back instead of levelling both to the sooner one.

    A consequence worth naming: if the source credit has already lapsed by the
    time the booking is cancelled, the restored row is born expired and
    `is_spendable` refuses it. That is what keeping the original expiry means,
    and the alternative is the extension loophole above.
    """
    now = now or timezone.now()
    restored = []
    for redemption in appointment.credit_redemptions.select_related("credit").all():
        source = redemption.credit
        restored.append(
            Credit.objects.create(
                shop=source.shop,
                client=source.client,
                amount_kes=redemption.amount_kes,
                remaining_kes=redemption.amount_kes,
                source=CreditSource.BOOKING_REFUNDED,
                # The same payment the original descends from. §5's carve-out
                # treats a credit-covered booking as verified *because* this
                # chain reaches a real M-Pesa success; breaking it here would
                # quietly make the restored credit unusable for that.
                source_payment=source.source_payment,
                source_appointment=appointment,
                expires_at=source.expires_at,
                reference=_unique_reference(),
                # Left OPEN even when `expires_at` is already past: `is_spendable`
                # reads the timestamp rather than the column for exactly this
                # window, and `expire_lapsed` tidies the column on its own sweep.
                state=CreditState.OPEN,
            )
        )
    return restored


def expire_lapsed(*, now=None, limit=500):
    """Flip lapsed credits to EXPIRED. Returns how many.

    Bookkeeping only — `is_spendable` already refuses an expired row, so this
    cannot lose a client money that a race would otherwise have let them spend.
    It exists so the exception queue and slice 9's reporting can distinguish
    "expired unused" from "still open", which is the number that tells a shop
    whether its credit policy is working.
    """
    now = now or timezone.now()
    lapsed = list(
        Credit.objects.unscoped()
        .filter(state=CreditState.OPEN, expires_at__lte=now)
        .values_list("pk", flat=True)[:limit]
    )
    if not lapsed:
        return 0
    return (
        Credit.objects.unscoped()
        .filter(pk__in=lapsed)
        .update(state=CreditState.EXPIRED, updated_at=now)
    )
