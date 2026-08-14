"""The exception queue, and the support-code lookup.

This is the whole of slice 6's answer to "the client rings the shop". The owner
dashboard is slice 9; a support code nobody can look up until then is decoration
on the one screen where the client is already unhappy, so the lookup ships here.

Two things this has to do in under a minute, with a client on the phone:

1. **Search by support code.** They read `BK-4F7K2Q` off screen 8 and somebody
   types it in. `search_fields` covers the code, the M-Pesa receipt and the
   number, because a distressed client will offer whichever of the three they
   can find.
2. **Show the queue.** `PaidWithNoBookingFilter` is the default view a shop
   wants: every succeeded payment with no booking to sit against, newest first,
   with the reason, the number to ring and the amount to talk about.

Everything is read-only. Money records are not edited in an admin form — a
payment moves through `payments/machine.py` or it does not move, and an admin
that can set `state = succeeded` by hand is an admin that can confirm a booking
nobody paid for.
"""

from django.contrib import admin

from payments.models import MpesaCallback, Payment, PaymentMove
from payments.states import PaymentState


class PaidWithNoBookingFilter(admin.SimpleListFilter):
    """The queue the shop actually works from."""

    title = "needs a human"
    parameter_name = "queue"

    def lookups(self, request, model_admin):
        return [
            ("orphaned", "Paid, no booking"),
            ("unknown", "Unresolved with M-Pesa"),
            ("discrepancy", "M-Pesa sent conflicting results"),
        ]

    def queryset(self, request, queryset):
        if self.value() == "orphaned":
            return queryset.filter(state=PaymentState.ORPHANED)
        if self.value() == "unknown":
            return queryset.filter(state=PaymentState.UNKNOWN)
        if self.value() == "discrepancy":
            return queryset.filter(discrepancy_count__gt=0)
        return queryset


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "support_code",
        "state",
        "amount",
        "phone",
        "orphan_reason",
        "shop_name",
        "when",
        "created_at",
    )
    list_filter = (PaidWithNoBookingFilter, "state", "orphan_reason")
    # The three things a client can read out. Exact-match on the code (`=`)
    # because it is one, and a `LIKE` over a money table is a table scan.
    search_fields = ("=support_code", "mpesa_receipt", "phone", "checkout_request_id")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    readonly_fields = [field.name for field in Payment._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        # `.unscoped()` is the sanctioned escape for admin tooling — CLAUDE.md
        # §3 names it explicitly. A support code is global by design: the client
        # rings, the shop searches, and neither knows an organization id.
        return Payment.objects.unscoped().select_related(
            "appointment", "appointment__shop", "appointment__staff"
        )

    @admin.display(description="Shop")
    def shop_name(self, payment):
        return payment.appointment.shop.name

    @admin.display(description="Appointment")
    def when(self, payment):
        from scheduling.availability import LOCAL_TZ

        local = payment.appointment.starts_at.astimezone(LOCAL_TZ)
        return f"{local:%a %d %b %H:%M} · {payment.appointment.staff.display_name}"


@admin.register(MpesaCallback)
class MpesaCallbackAdmin(admin.ModelAdmin):
    """Evidence. Append-only at the model, read-only here.

    The payload is stored with the payer's number redacted (CLAUDE.md §5), so
    this list is safe to open in front of somebody.
    """

    list_display = ("checkout_request_id", "outcome", "result_code", "created_at")
    list_filter = ("outcome",)
    search_fields = ("checkout_request_id", "merchant_request_id")
    ordering = ("-created_at",)
    readonly_fields = [field.name for field in MpesaCallback._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PaymentMove)
class PaymentMoveAdmin(admin.ModelAdmin):
    """Empty until slice 7. Registered now so the audit trail is visible from
    the first move rather than from the first bug report."""

    list_display = ("payment", "from_appointment", "to_appointment", "reason", "created_at")
    ordering = ("-created_at",)
    readonly_fields = [field.name for field in PaymentMove._meta.fields]

    def get_queryset(self, request):
        return PaymentMove.objects.unscoped().select_related("payment")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
