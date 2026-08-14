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

from django import forms
from django.contrib import admin, messages
from django.db import models
from django.shortcuts import redirect, render
from django.utils import timezone

from payments.credit import Credit, CreditRedemption
from payments.models import MpesaCallback, Payment, PaymentMove
from payments.states import PaymentState


class PaidWithNoBookingFilter(admin.SimpleListFilter):
    """The queue the shop actually works from."""

    title = "needs a human"
    parameter_name = "queue"

    def lookups(self, request, model_admin):
        return [
            ("open", "Open — needs a human"),
            ("refund_due", "Refund owed to the client"),
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
        if self.value() == "refund_due":
            return queryset.filter(refund_due_at__isnull=False, queue_resolved_at__isnull=True)
        if self.value() == "open":
            # The default working view. Everything needing a human that nobody
            # has finished with — slice 7. Without it the queue only grows, and
            # a queue that never empties is one nobody opens.
            return queryset.filter(queue_resolved_at__isnull=True).filter(
                models.Q(state__in=(PaymentState.ORPHANED, PaymentState.UNKNOWN))
                | models.Q(discrepancy_count__gt=0)
                # Slice 7. A refund the shop owes is exactly as much "needs a
                # human" as a payment with no booking, and it is money going the
                # other way — so it belongs in the same default view.
                | models.Q(refund_due_at__isnull=False)
            )
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


# ------------------------------------------------ slice 7: working the queue


class ResolveForm(forms.Form):
    """The note is required. A row marked done with no reason is a row that
    reappears as a mystery the next time somebody audits the month."""

    note = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={"size": 80}),
        help_text="What was done. Shown to whoever opens this row next.",
    )


class RepointForm(forms.Form):
    """Which hold to carry this deposit to.

    A free-text appointment id rather than a picker: the shop has just created
    the hold with the client on the phone, so they have the id in front of them,
    and a dropdown of every pending hold in the system is both a leak and
    unusable at any real size.
    """

    hold_id = forms.UUIDField(
        label="Target hold id",
        help_text=(
            "Create the new hold first (staff day view or the client's own "
            "screen), then paste its id here. It must be pending_payment, at "
            "the same shop, and its deposit must not exceed what was paid."
        ),
    )
    note = forms.CharField(
        max_length=255, required=False, widget=forms.TextInput(attrs={"size": 80})
    )


@admin.action(description="Mark as dealt with (adds a note)")
def mark_resolved(modeladmin, request, queryset):
    if "apply" in request.POST:
        form = ResolveForm(request.POST)
        if form.is_valid():
            # Captured before the update, because `refund_due_at` is what says
            # this row owed the client money and the client is the one who has
            # been waiting without being told anything.
            owed = list(
                queryset.filter(refund_due_at__isnull=False).select_related(
                    "appointment", "appointment__shop", "appointment__client"
                )
            )
            count = queryset.update(
                queue_resolved_at=timezone.now(),
                queue_resolved_by=request.user,
                queue_note=form.cleaned_data["note"],
            )
            told = _tell_them_the_refund_went(owed)
            modeladmin.message_user(
                request,
                f"{count} payment(s) marked as dealt with."
                + (f" {told} client(s) told the refund is on its way." if told else ""),
                messages.SUCCESS,
            )
            return redirect(request.get_full_path())
    else:
        form = ResolveForm()
    return render(
        request,
        "admin/payments/resolve.html",
        {
            "payments": queryset,
            "form": form,
            "action": "mark_resolved",
            "title": "Mark as dealt with",
        },
    )


@admin.action(description="Re-point this deposit to another hold")
def repoint_payment(modeladmin, request, queryset):
    """The staff-side of the `slotLost` remedy.

    The client-side is `public_api.lifecycle_views.RepointView` and shares the
    same `payments/repoint.repoint` — one implementation, so a shop doing it by
    hand and a client doing it themselves cannot produce different bookkeeping.

    One at a time on purpose. Each re-point needs its own target, and a bulk
    action that moved several deposits onto one slot would be a bug with money
    in it.
    """
    from payments.repoint import RepointRefused, is_repointable, notify_repointed, repoint
    from scheduling.booking import SlotTaken
    from scheduling.models import Appointment

    if queryset.count() != 1:
        modeladmin.message_user(
            request, "Select exactly one payment to re-point.", messages.WARNING
        )
        return None

    payment = queryset.first()
    if not is_repointable(payment):
        modeladmin.message_user(
            request,
            f"{payment.support_code} is not waiting for a booking "
            f"(state={payment.state}, reason={payment.orphan_reason or '—'}).",
            messages.WARNING,
        )
        return None

    if "apply" in request.POST:
        form = RepointForm(request.POST)
        if form.is_valid():
            target = (
                Appointment.objects.unscoped()
                .select_related("shop", "staff", "service", "client")
                .filter(pk=form.cleaned_data["hold_id"])
                .first()
            )
            if target is None:
                modeladmin.message_user(request, "No such appointment.", messages.ERROR)
                return redirect(request.get_full_path())
            try:
                repoint(payment, to_appointment=target, moved_by=request.user)
            except RepointRefused as exc:
                modeladmin.message_user(request, str(exc), messages.ERROR)
                return redirect(request.get_full_path())
            except SlotTaken:
                modeladmin.message_user(
                    request, "That slot was taken while you were working.", messages.ERROR
                )
                return redirect(request.get_full_path())

            payment.refresh_from_db()
            notify_repointed(target, payment)
            Payment.objects.unscoped().filter(pk=payment.pk).update(
                queue_resolved_at=timezone.now(),
                queue_resolved_by=request.user,
                queue_note=form.cleaned_data.get("note") or f"Re-pointed to {target.pk}",
            )
            modeladmin.message_user(
                request,
                f"{payment.support_code} re-pointed. The client has been sent a confirmation.",
                messages.SUCCESS,
            )
            return redirect(request.get_full_path())
    else:
        form = RepointForm()

    return render(
        request,
        "admin/payments/resolve.html",
        {
            "payments": queryset,
            "form": form,
            "action": "repoint_payment",
            "title": f"Re-point {payment.support_code} (KES {payment.amount})",
        },
    )


PaymentAdmin.actions = [mark_resolved, repoint_payment]
PaymentAdmin.list_display = (*PaymentAdmin.list_display, "queue_state")
PaymentAdmin.list_filter = (*PaymentAdmin.list_filter, "queue_resolved_at")


@admin.display(description="Queue", boolean=False)
def queue_state(self, payment):
    if payment.queue_resolved_at is None:
        return "open"
    who = payment.queue_resolved_by.phone if payment.queue_resolved_by_id else "system"
    return f"done · {who} · {payment.queue_note[:40]}"


PaymentAdmin.queue_state = queue_state


@admin.register(Credit)
class CreditAdmin(admin.ModelAdmin):
    """What a shop owes its clients in unspent credit.

    Read-only for the same reason `PaymentAdmin` is: this is money. A credit is
    issued by a cancellation going through `scheduling/lifecycle.cancel` or it
    is not issued, and an admin form that could mint one by hand is an admin
    form that can hand out a shop's takings.

    Voiding exists and is not editing: `CreditState.CANCELLED` is a decision
    somebody made, which is why it is a column rather than derived from the
    numbers. It is not wired to an action here — no shop has asked, and a
    button that takes a client's money away should not be the easy path.
    """

    list_display = (
        "reference",
        "client",
        "shop",
        "amount_kes",
        "remaining_kes",
        "state",
        "expires_at",
        "source",
    )
    list_filter = ("state", "source", "shop")
    search_fields = ("=reference", "client__phone", "client__full_name")
    ordering = ("expires_at",)
    date_hierarchy = "expires_at"
    readonly_fields = [field.name for field in Credit._meta.fields]

    def get_queryset(self, request):
        return Credit.objects.unscoped().select_related("client", "shop", "source_payment")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CreditRedemption)
class CreditRedemptionAdmin(admin.ModelAdmin):
    """Where a credit went. Append-only; the running total on `Credit` is a
    number, and this is the story a client disputing a balance needs."""

    list_display = ("credit", "appointment", "amount_kes", "created_at")
    search_fields = ("=credit__reference",)
    ordering = ("-created_at",)
    readonly_fields = [field.name for field in CreditRedemption._meta.fields]

    def get_queryset(self, request):
        return CreditRedemption.objects.unscoped().select_related("credit", "appointment")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


def _tell_them_the_refund_went(payments):
    """Close the loop on a refund the shop has just sent. Slice 8.

    `scheduling.lifecycle.cancel` records what is owed and can do no more —
    we are not the merchant, so the transfer is the shop's to make and we never
    learn that it happened. Marking the queue row done *is* that signal, and it
    is the only one there is.

    Without this the client's last word from us is "the shop will refund you",
    with no closing line and no recourse but to ring and ask.
    """
    from notifications.service import queue_message
    from notifications.templates import Template
    from scheduling.lifecycle import paid_deposit_for
    from scheduling.statuses import BookingSource

    told = 0
    for payment in payments:
        appointment = payment.appointment
        if appointment.source != BookingSource.ONLINE or appointment.client_id is None:
            continue
        sent = queue_message(
            appointment,
            Template.REFUND_SENT,
            variables_extra={"paid": f"{paid_deposit_for(appointment):,}"},
        )
        if sent is not None:
            told += 1
    return told
