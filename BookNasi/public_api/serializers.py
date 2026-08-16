"""Serializers for the unauthenticated public booking surface.

**These share no code with `shops/serializers.py`, deliberately.**

CLAUDE.md §1: "Build every API as if a third party will integrate it, because
one will." The tempting version of this module is to import `ShopSerializer`
and subclass it with a shorter `fields` list. That fails the first time someone
adds a field to the parent — the new field appears on the public endpoint
silently, because `fields` on the parent is what changed, not the child. The
same trap exists for a single serializer with an `if request.user` branch.

So the classes here are written out in full, declare their fields explicitly,
and are tested by asserting the exact field set. Duplication is the point: the
two surfaces are meant to be able to diverge without either dragging the other
along.

What must never appear here:

- `organization`, or anything that reveals which tenant owns the shop
- `buffer_minutes` — internal scheduling policy, not the client's business
- `is_active`, `is_publicly_listed` — a hidden row is simply absent instead
- staff `membership`, which links to a user account

What must appear here, because the client cannot complete a booking without it:

- `hold_ttl_minutes`, which drives the visible countdown (CLAUDE.md §10)
- `refund_window_hours`, because the refund rule is stated *before* payment
- `deposit_amount`, the exact figure that will be pushed to M-Pesa
"""

from rest_framework import serializers

from shops.models import OpeningHours, Service, Shop, Staff


def _client_message_for(payment):
    """The safe sentence screen 7 shows. Never Safaricom's raw `ResultDesc`.

    Two sources, because a payment can fail in two places. A callback brings a
    `ResultCode` and `RESULT_MESSAGES` maps it. A push Safaricom refused
    outright never gets that far — it carries only a `result_desc` from the push
    call — and left unhandled it produced an empty string, so screen 7 named a
    failure and then gave no reason for it.
    """
    from payments.messages import client_message, push_not_sent_message
    from payments.states import PaymentState

    if payment.result_code not in (None, 0):
        return client_message(payment.result_code)
    if payment.state == PaymentState.PUSH_FAILED:
        return push_not_sent_message()
    return ""


class PublicOpeningHoursSerializer(serializers.Serializer):
    weekday = serializers.IntegerField(read_only=True)
    opens_at = serializers.TimeField(read_only=True)
    closes_at = serializers.TimeField(read_only=True)

    class Meta:
        model = OpeningHours


class PublicShopSerializer(serializers.Serializer):
    """Explicit fields, not a ModelSerializer.

    A `ModelSerializer` with `exclude` would leak any future column by default;
    one with `fields` would still inherit `Meta` changes. Declaring each field
    by hand means a new model column reaches this endpoint only when someone
    writes a line here.
    """

    slug = serializers.SlugField(read_only=True)
    name = serializers.CharField(read_only=True)
    address = serializers.CharField(read_only=True)
    area = serializers.CharField(read_only=True)
    directions_url = serializers.URLField(read_only=True)
    phone = serializers.CharField(read_only=True)
    logo_url = serializers.URLField(read_only=True)
    accent_color = serializers.CharField(read_only=True)
    # Drives the hold countdown. The countdown is not themeable and not
    # hideable — CLAUDE.md §10 — so the client has to be told its length.
    hold_ttl_minutes = serializers.IntegerField(read_only=True)
    # The refund rule is shown before payment, never after. Both halves of it:
    # the window, and how long a late cancellation's credit lasts. CLAUDE.md §12
    # settled the terms on 14 August 2026 and §5 requires the client to read
    # them before they pay, which means the public API has to carry them.
    refund_window_hours = serializers.IntegerField(read_only=True)
    deposit_credit_days = serializers.IntegerField(read_only=True)
    opening_hours = serializers.SerializerMethodField()

    class Meta:
        model = Shop

    def get_opening_hours(self, shop):
        rows = shop.opening_hours.order_by("weekday")
        return PublicOpeningHoursSerializer(rows, many=True).data


class PublicServiceSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    duration_minutes = serializers.IntegerField(read_only=True)
    price = serializers.IntegerField(read_only=True)
    deposit_mode = serializers.CharField(read_only=True)
    #: The figure the client is shown and the figure slice 6 pushes to M-Pesa.
    #: One number, computed once, by shops.money.deposit_amount.
    deposit_amount = serializers.IntegerField(read_only=True)
    balance_due = serializers.SerializerMethodField()

    class Meta:
        model = Service

    def get_balance_due(self, service):
        """What is still owed at the shop. The design shows this on the confirm
        card next to the deposit, so it is computed here rather than in the
        client, where a rounding difference would show up as a wrong number."""
        return max(service.price - service.deposit_amount, 0)


class HoldRequestSerializer(serializers.Serializer):
    """What the confirm step sends. Input only.

    No name and no email. CLAUDE.md §12: the phone number is the whole of the
    client's identity, and the STK push to it is the verification. Asking for
    anything else here would be a field that costs bookings and buys nothing —
    the shop learns the name when the client sits down.
    """

    service = serializers.UUIDField()
    #: Required, even when the client picked "anyone available". The
    #: availability response names the stylist who owns each start precisely so
    #: this can be concrete — `Appointment.staff` is not nullable and the
    #: exclusion constraint is per staff member.
    staff = serializers.UUIDField()
    starts_at = serializers.DateTimeField()
    phone = serializers.CharField(max_length=20)
    #: Same guard as the staff app's walk-in: a client on 3G who taps Confirm,
    #: sees nothing, and taps again must not create two holds and be told the
    #: second collided with the first.
    client_request_id = serializers.CharField(required=False, allow_blank=True, max_length=64)

    def validate_phone(self, value):
        from accounts.phone import InvalidPhoneNumber, normalize_phone

        try:
            return normalize_phone(value)
        except InvalidPhoneNumber as exc:
            # The library message names the accepted formats, which is what a
            # client mistyping their own number actually needs.
            raise serializers.ValidationError(str(exc)) from exc


class PublicHoldSerializer(serializers.Serializer):
    """The held slot, as the client's countdown screen needs it.

    Deliberately thin. This is an unauthenticated endpoint keyed by an
    unguessable id, and everything it returns is either something the caller
    just sent or something already on the public service list. No client name,
    no other bookings, nothing about the shop's day.
    """

    id = serializers.UUIDField(read_only=True)
    status = serializers.CharField(read_only=True)
    starts_at = serializers.DateTimeField(read_only=True)
    ends_at = serializers.DateTimeField(read_only=True)
    local_time = serializers.SerializerMethodField()
    hold_expires_at = serializers.DateTimeField(read_only=True)
    #: Seconds left, computed server-side at the moment of the response. The
    #: countdown is a rendering of this and never the thing that decides — a
    #: client whose clock is wrong must still be told the truth about the slot.
    seconds_remaining = serializers.SerializerMethodField()
    staff_name = serializers.SerializerMethodField()
    service_name = serializers.SerializerMethodField()
    price_kes = serializers.IntegerField(source="price_snapshot", read_only=True)
    deposit_kes = serializers.IntegerField(source="deposit_snapshot", read_only=True)
    balance_kes = serializers.SerializerMethodField()
    #: What has actually been credited to this booking — M-Pesa and spent shop
    #: credit together. Distinct from `deposit_kes`, which after
    #: `holds.apply_credit` is only what is still owed to M-Pesa and is zero for
    #: a booking whose deposit shop credit covered outright. The paid screen led
    #: with "KES 0 received" for exactly that case until slice 11.
    paid_kes = serializers.SerializerMethodField()
    #: Slice 6. The countdown has to be able to say "still checking with M-Pesa"
    #: rather than "expired" — see `get_payment`.
    payment = serializers.SerializerMethodField()
    shop_phone = serializers.SerializerMethodField()
    shop_name = serializers.SerializerMethodField()
    #: The refund terms, again. They are on the confirm screen before payment
    #: (CLAUDE.md §5) and they are here because the confirmation SMS links to
    #: the booking's own page, and a client reading the terms afterwards should
    #: find the same sentence rather than have to remember it. Two integers, not
    #: prose: the copy is the client's to render and relabel — §10 — and the
    #: policy behind it is §12's.
    refund_window_hours = serializers.SerializerMethodField()
    deposit_credit_days = serializers.SerializerMethodField()

    def get_shop_name(self, appointment):
        return appointment.shop.name

    def get_refund_window_hours(self, appointment):
        return appointment.shop.refund_window_hours

    def get_deposit_credit_days(self, appointment):
        return appointment.shop.deposit_credit_days

    def get_shop_phone(self, appointment):
        """The number on screen 5's fallback line and screen 8's footer.

        Public already: it is on the shop's own booking page header.
        """
        return appointment.shop.phone

    def get_payment(self, appointment):
        """What the STK waiting screen renders itself from.

        Four things, and each one is on a screen:

        - `state` drives screens 5 → 6 / 7 / 8. It is the *payment's* state, not
          the appointment's, because those are two machines and the client is
          watching the money one.
        - `push_outstanding` is the fact the countdown needs. Without it a
          client whose timer reaches 0:00 while Safaricom is still thinking is
          told the slot expired, which is the unexplained failure CLAUDE.md §10
          invariant 3 exists to prevent. With it the screen says "still checking
          with M-Pesa" and stays honest.
        - `message` is client-safe copy, never Safaricom's raw ResultDesc.
          Screen 7 names the reason; `payments/messages.py` decides which
          reasons are safe to name.
        - `support_code` is what screen 8 shows and what the client reads down
          the phone. Present as soon as a push exists, because the case it is
          for is the one where nothing else worked.

        The M-Pesa receipt is here too — screen 6 puts it above everything else,
        since it is the client's proof at the door.
        """
        from payments.states import OrphanReason, PaymentState
        from payments.stk import outstanding_push

        payment = appointment.payments.order_by("-created_at").first()
        if payment is None:
            return None
        return {
            "state": payment.state,
            "amount_kes": payment.amount,
            "support_code": payment.support_code,
            "mpesa_receipt": payment.mpesa_receipt,
            "push_outstanding": outstanding_push(appointment),
            "message": _client_message_for(payment),
            # ORPHANED is not enough on its own. `settle_succeeded` orphans for
            # four reasons and only one of them is the lost race screen 8
            # describes; the other three leave the booking intact. Combined with
            # this serializer always reporting the *newest* payment, a client who
            # answered two prompts would be shown "your slot was taken, the shop
            # will call" over a booking that is confirmed and paid for.
            "slot_lost": (
                payment.state == PaymentState.ORPHANED
                and payment.orphan_reason == OrphanReason.SLOT_LOST
            ),
        }

    def get_local_time(self, appointment):
        from scheduling.availability import LOCAL_TZ

        return appointment.starts_at.astimezone(LOCAL_TZ).strftime("%H:%M")

    def get_seconds_remaining(self, appointment):
        from django.utils import timezone

        if appointment.hold_expires_at is None:
            return 0
        return max(0, int((appointment.hold_expires_at - timezone.now()).total_seconds()))

    def get_staff_name(self, appointment):
        return appointment.staff.display_name

    def get_service_name(self, appointment):
        return appointment.service.name

    def get_balance_kes(self, appointment):
        from scheduling.lifecycle import balance_due_for

        return balance_due_for(appointment)

    def get_paid_kes(self, appointment):
        from scheduling.lifecycle import paid_deposit_for

        return paid_deposit_for(appointment)


class PublicStaffSerializer(serializers.Serializer):
    """No membership, no user id, no phone. A client picking a stylist needs a
    name and a duration, and nothing that identifies an account."""

    id = serializers.UUIDField(read_only=True)
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = Staff


class ManageViewSerializer(serializers.Serializer):
    """What the manage page renders. Slice 7.

    Wider than `PublicHoldSerializer` because this page can act, and a button
    whose consequence is not on screen is worse than no button — CLAUDE.md §5
    requires the terms to be readable before money moves, and on the cancel
    screen the term that matters is the *figure*.

    `actions` is computed by `scheduling/lifecycle.actions_for`, the same
    function the cancel endpoint applies, so the screen and the write cannot
    disagree about what a client is owed.

    Still narrow on identity. This is unauthenticated, keyed by a token that
    reached one phone: no client name, no other bookings, nothing about the
    shop's day.
    """

    id = serializers.UUIDField(read_only=True)
    status = serializers.CharField(read_only=True)
    starts_at = serializers.DateTimeField(read_only=True)
    ends_at = serializers.DateTimeField(read_only=True)
    local_time = serializers.SerializerMethodField()
    local_date = serializers.SerializerMethodField()
    staff_name = serializers.SerializerMethodField()
    staff_id = serializers.SerializerMethodField()
    service_name = serializers.SerializerMethodField()
    service_id = serializers.SerializerMethodField()
    price_kes = serializers.IntegerField(source="price_snapshot", read_only=True)
    deposit_kes = serializers.IntegerField(source="deposit_snapshot", read_only=True)
    balance_kes = serializers.SerializerMethodField()
    paid_kes = serializers.SerializerMethodField()
    shop_name = serializers.SerializerMethodField()
    shop_slug = serializers.SerializerMethodField()
    shop_phone = serializers.SerializerMethodField()
    refund_window_hours = serializers.SerializerMethodField()
    deposit_credit_days = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()
    credit = serializers.SerializerMethodField()

    def get_local_time(self, appointment):
        from scheduling.availability import LOCAL_TZ

        return appointment.starts_at.astimezone(LOCAL_TZ).strftime("%H:%M")

    def get_local_date(self, appointment):
        from scheduling.availability import LOCAL_TZ

        return appointment.starts_at.astimezone(LOCAL_TZ).strftime("%Y-%m-%d")

    def get_staff_name(self, appointment):
        return appointment.staff.display_name

    def get_staff_id(self, appointment):
        return str(appointment.staff_id)

    def get_service_name(self, appointment):
        return appointment.service.name

    def get_service_id(self, appointment):
        return str(appointment.service_id)

    def get_balance_kes(self, appointment):
        from scheduling.lifecycle import balance_due_for

        return balance_due_for(appointment)

    def get_paid_kes(self, appointment):
        from scheduling.lifecycle import paid_deposit_for

        return paid_deposit_for(appointment)

    def get_shop_name(self, appointment):
        return appointment.shop.name

    def get_shop_slug(self, appointment):
        return appointment.shop.slug

    def get_shop_phone(self, appointment):
        return appointment.shop.phone or ""

    def get_refund_window_hours(self, appointment):
        return appointment.shop.refund_window_hours

    def get_deposit_credit_days(self, appointment):
        return appointment.shop.deposit_credit_days

    def get_actions(self, appointment):
        from scheduling.lifecycle import actions_for

        return actions_for(appointment)

    def get_credit(self, appointment):
        """Spendable credit this client holds at this shop, if any.

        On the manage page because it is the page a client opens after a late
        cancellation, and "you have KES 875 until 13 October" is the whole
        reason credit is not a forfeit.
        """
        from payments.credit import balance_for, spendable_for

        if appointment.client_id is None:
            return None
        balance = balance_for(appointment.client, appointment.shop)
        if balance < 1:
            return None
        soonest = spendable_for(appointment.client, appointment.shop).first()
        return {
            "balance_kes": balance,
            "expires_at": soonest.expires_at if soonest else None,
            "reference": soonest.reference if soonest else "",
        }
