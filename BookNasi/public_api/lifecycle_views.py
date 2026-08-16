"""The manage surface. Everything a client can do to their own booking.

Authenticated by the token in the URL and nothing else — CLAUDE.md §12, "the
link is the session". `scheduling/manage_tokens` owns what that means; every
view here goes through `resolve` so expiry, revocation and the no-existence-
oracle rule are decided once instead of re-argued per endpoint.

## Every failure is the same 404

A bad token, an unknown token, a revoked token and an expired one all return an
identical 404 with no body detail. Distinguishing them would turn this into an
oracle: "expired" confirms a booking exists, and that is the one fact a caller
must not be able to learn by probing. `ManageTokenInvalid` carries no message
for the same reason.

## Its own throttle scopes

Per the rule in `scheduling/abuse.py`, and here it matters more than usual: this
is the only unauthenticated surface that *writes*. The read is polled by a page
a client may leave open; the writes are once-per-booking actions. Sharing a
budget between them would let a left-open tab spend a client's ability to cancel.

## Referrer-Policy

The token is in the URL, so without `no-referrer` the whole credential leaks in
the `Referer` header to anything the page loads. Set on every response here
rather than on the page alone, because an API response fetched from a page is
subject to the same header.
"""

import logging

from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from clients import erasure
from payments.credit import Credit, CreditSource
from public_api.serializers import ManageViewSerializer
from scheduling import lifecycle, manage_tokens

logger = logging.getLogger(__name__)


class ManageBaseView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get_appointment(self, token):
        from django.http import Http404

        try:
            return manage_tokens.resolve(token)
        except manage_tokens.ManageTokenInvalid as exc:
            # One shape for every failure. See the module docstring.
            raise Http404 from exc

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Referrer-Policy"] = "no-referrer"
        return response

    def rendered(self, appointment):
        return Response(ManageViewSerializer(appointment).data)


class ManageDetailView(ManageBaseView):
    """`GET /api/public/v1/manage/<token>/` — the booking, and what can be done.

    Stamps the refund-window latch on the way past. That is not a side effect
    smuggled into a read: the latch records that the booking *has been* inside
    its window, and a client opening the manage page inside the window is the
    most reliable observation of that we will ever get. Doing it on a schedule
    would mean a sweep frequent enough to catch every booking crossing its own
    boundary, and being late there silently hands out refunds.
    """

    throttle_scope = "manage-read"

    def get(self, request, token):
        appointment = self.get_appointment(token)
        lifecycle.stamp_window(appointment)
        return self.rendered(appointment)


@method_decorator(csrf_exempt, name="dispatch")
class ManageCancelView(ManageBaseView):
    """`POST /api/public/v1/manage/<token>/cancel/`

    The figure the client was shown before confirming is recomputed here and not
    trusted from the request. A client who left the screen open across the
    refund boundary must get what the policy says now, not what it said an hour
    ago — and a request that could name its own refund amount would be the worst
    possible thing to accept on an unauthenticated endpoint.
    """

    throttle_scope = "manage-cancel"

    def post(self, request, token):
        appointment = self.get_appointment(token)
        try:
            outcome, amount, credit = lifecycle.cancel(appointment)
        except lifecycle.NotManageable as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

        appointment.refresh_from_db()
        # A refundable cancellation of a deposit paid with shop credit returns
        # that part as credit, not as cash — `payments.credit.restore`. The
        # screen has to say so for the same reason the SMS does: "the shop will
        # refund you" would leave the client waiting for a transfer nobody is
        # sending. Read back rather than threaded through `lifecycle.cancel`'s
        # return, which is a tuple three callers already unpack.
        restored = list(
            Credit.objects.unscoped().filter(
                source_appointment=appointment, source=CreditSource.BOOKING_REFUNDED
            )
        )
        body = ManageViewSerializer(appointment).data
        body["result"] = {
            "outcome": outcome,
            "amount_kes": amount,
            "credit_reference": credit.reference if credit else "",
            "credit_expires_at": credit.expires_at if credit else None,
            #: How much of `amount_kes` went back as credit. Zero for an
            #: ordinary M-Pesa deposit, which is the common case and reads
            #: exactly as it always did.
            "restored_kes": sum(row.amount_kes for row in restored),
            "restored_reference": restored[0].reference if len(restored) == 1 else "",
        }
        return Response(body)


@method_decorator(csrf_exempt, name="dispatch")
@method_decorator(csrf_exempt, name="dispatch")
class ManageForgetMeView(ManageBaseView):
    """`POST /api/public/v1/manage/<token>/forget-me/` — the client asks.

    CLAUDE.md §9 gives a data subject a delete path, and until slice 14 the only
    one was ringing the salon. The manage token is the natural place for it: it
    is the session (§12), and it proves control of the phone number — the same
    verification the deposit relies on.

    **It records a request; it does not erase.** Two reasons, and the second is
    the one that decided it:

    - Erasure is irreversible and voids any unspent credit. One tap on a phone,
      on a link that arrived by SMS, is too easy a way to reach that — and
      unlike cancelling, there is no version of it the shop can undo.
    - The organization is the controller (§9), so the obligation is theirs to
      discharge and the record of discharging it is theirs to hold. A silent
      automatic scrub would leave them with nothing to show a regulator except
      an absence.

    Idempotent, and it keeps the first timestamp. The DPA clock starts when the
    person asked, not when they last pressed the button, so a second tap must
    not restart it — that would let a shop reset its own deadline by prompting.
    """

    throttle_scope = "manage-forget-me"

    def post(self, request, token):
        appointment = self.get_appointment(token)
        client = appointment.client
        if client is None:
            # A walk-in with no client row. Nothing personal is held, so there
            # is nothing to ask about — and answering differently here would
            # tell an anonymous caller whether a record existed.
            return Response({"requested": True, "statement": erasure.retention_statement()})

        if client.erasure_requested_at is None:
            client.erasure_requested_at = timezone.now()
            client.save(update_fields=["erasure_requested_at", "updated_at"])

        return Response(
            {
                "requested": True,
                "requested_at": client.erasure_requested_at.isoformat(),
                "statement": erasure.retention_statement(),
            }
        )


class ManageRescheduleView(ManageBaseView):
    """`POST /api/public/v1/manage/<token>/reschedule/`

    One booking, one move, no cascade — CLAUDE.md §8. `starts_at` is re-derived
    against the engine and then decided by the exclusion constraint, so a
    walk-in recorded into the target slot a moment ago wins and the client is
    told to pick again.
    """

    throttle_scope = "manage-reschedule"

    def post(self, request, token):
        from rest_framework import serializers as drf

        from scheduling.booking import SlotTaken

        appointment = self.get_appointment(token)

        class Form(drf.Serializer):
            starts_at = drf.DateTimeField()
            staff = drf.UUIDField(required=False, allow_null=True)

        form = Form(data=request.data)
        form.is_valid(raise_exception=True)

        staff = None
        if form.validated_data.get("staff"):
            from django.shortcuts import get_object_or_404

            from shops.models import Staff

            staff = get_object_or_404(
                Staff.objects.unscoped().filter(
                    shop=appointment.shop, is_active=True, is_bookable=True
                ),
                pk=form.validated_data["staff"],
            )

        try:
            lifecycle.reschedule(
                appointment, starts_at=form.validated_data["starts_at"], staff=staff
            )
        except lifecycle.RescheduleRefused as exc:
            code = (
                status.HTTP_409_CONFLICT
                if exc.reason == "slot_taken"
                else status.HTTP_400_BAD_REQUEST
            )
            return Response({"detail": str(exc), "reason": exc.reason}, status=code)
        except SlotTaken:
            # The constraint, not the check above. Somebody took it in between.
            return Response(
                {"detail": "That time was just taken. Pick another.", "reason": "slot_taken"},
                status=status.HTTP_409_CONFLICT,
            )

        appointment.refresh_from_db()
        return self.rendered(appointment)


# ------------------------------------------------------- the slotLost remedy


@method_decorator(csrf_exempt, name="dispatch")
class RepointView(APIView):
    """`POST /api/public/v1/payments/<support_code>/repoint/`

    The `slotLost` remedy, option B: the client picks another time and their
    deposit comes with it. Keyed by the support code rather than a manage token
    because there is no booking to manage — the appointment they held was
    cancelled when the slot went, and the support code is what screen 8 already
    shows them and what they would otherwise be reading down a phone.

    That makes the support code a credential, so it is bounded like one: its own
    throttle scope, and a re-point that only ever moves money the *holder of that
    code* already paid onto a slot they just held themselves. There is nothing to
    steal by guessing one — the worst a guesser achieves is confirming somebody
    else's booking with somebody else's money, which is why the target must be a
    `pending_payment` hold created in the same session and belonging to the same
    shop.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "payment-repoint"

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Referrer-Policy"] = "no-referrer"
        return response

    def post(self, request, support_code):
        from django.http import Http404
        from rest_framework import serializers as drf

        from payments.models import Payment
        from payments.repoint import RepointRefused, is_repointable, notify_repointed, repoint
        from scheduling.booking import SlotTaken
        from scheduling.models import Appointment

        class Form(drf.Serializer):
            hold = drf.UUIDField()

        form = Form(data=request.data)
        form.is_valid(raise_exception=True)

        payment = (
            Payment.objects.unscoped()
            .select_related("appointment", "appointment__shop")
            .filter(support_code=support_code)
            .first()
        )
        # Same 404 for unknown and not-repointable, for the reason the manage
        # views give: a different answer for each turns this into an oracle for
        # which support codes exist.
        if payment is None or not is_repointable(payment):
            raise Http404

        target = get_object_or_404_hold(Appointment, form.validated_data["hold"])

        try:
            appointment = repoint(payment, to_appointment=target)
        except RepointRefused as exc:
            return Response(
                {"detail": str(exc), "reason": exc.reason}, status=status.HTTP_400_BAD_REQUEST
            )
        except SlotTaken:
            return Response(
                {"detail": "That time was just taken. Pick another.", "reason": "slot_taken"},
                status=status.HTTP_409_CONFLICT,
            )

        payment.refresh_from_db()
        notify_repointed(appointment, payment)
        appointment.refresh_from_db()
        return Response(ManageViewSerializer(appointment).data, status=status.HTTP_200_OK)


def get_object_or_404_hold(model, pk):
    from django.shortcuts import get_object_or_404

    return get_object_or_404(
        model.objects.unscoped().select_related("shop", "staff", "service", "client"), pk=pk
    )
