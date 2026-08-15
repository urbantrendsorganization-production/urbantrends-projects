"""The unauthenticated booking surface.

Shop-scoped by slug, never org-scoped. There is no request user here and no
membership to check, so isolation comes from the lookup itself: a shop is found
by its public slug, and everything below it is filtered to that shop.

Slice 5 adds availability and hold creation here. Slice 10's widget and any
third-party integrator consume this and only this.
"""

import logging

from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from payments.stk import PushRefused, initiate_push, resend_push
from public_api.serializers import (
    HoldRequestSerializer,
    PublicHoldSerializer,
    PublicServiceSerializer,
    PublicShopSerializer,
    PublicStaffSerializer,
)
from scheduling.abuse import HoldRefused
from scheduling.booking import SlotTaken, SlotUnavailable
from scheduling.holds import (
    ServiceNotPubliclyBookable,
    confirm_credit_covered,
    create_hold,
    release_hold,
)
from scheduling.models import Appointment
from scheduling.statuses import BookingSource
from shops.durations import ServiceNotOffered
from shops.models import Service, Shop, Staff, StaffService

logger = logging.getLogger(__name__)


class PublicViewMixin:
    permission_classes = [AllowAny]
    authentication_classes = []
    #: **No default, on purpose.** Every public endpoint declares its own
    #: throttle scope — see the rule and its two-slice history in
    #: `scheduling/abuse.py`. A shared default is not "these endpoints together
    #: get N/hour"; under carrier-grade NAT it is "one client's traffic can
    #: exhaust the allowance of every stranger on their operator's NAT pool",
    #: and the 429 lands on whichever endpoint they touch next. Inheriting a
    #: scope by accident is exactly how `hold-detail`'s 3-second poll ended up
    #: starving the shop and availability reads in slice 6.
    #:
    #: `None` here means DRF applies no scoped rate at all, so forgetting one is
    #: an unthrottled endpoint rather than a silently shared budget. That is the
    #: safer failure of the two — and `core/tests/test_throttle_scopes.py`
    #: refuses to let either ship.
    throttle_scope = None

    def get_shop(self):
        # `.unscoped()` is correct here and is the reason it is greppable: this
        # surface has no request user and no organization to scope by. The slug
        # *is* the scope — it resolves to exactly one shop in one tenant, and
        # everything below is then filtered to that shop.
        #
        # Only active shops are reachable. A deactivated shop's booking page is
        # gone, which is the point of deactivating it.
        return get_object_or_404(
            Shop.objects.unscoped().filter(is_active=True), slug=self.kwargs["slug"]
        )


class PublicShopDetailView(PublicViewMixin, APIView):
    throttle_scope = "shop-read"

    def get(self, request, slug):
        return Response(PublicShopSerializer(self.get_shop()).data)


class PublicServiceListView(PublicViewMixin, generics.ListAPIView):
    throttle_scope = "service-read"
    serializer_class = PublicServiceSerializer
    pagination_class = None

    def get_queryset(self):
        # `publicly_bookable()` encodes CLAUDE.md §12's locked decision in SQL:
        # active, listed, and carrying an actual deposit. A deposit-free service
        # is absent from this list — not shown-and-rejected — because the client
        # should never see something they cannot book.
        return (
            Service.objects.for_org(self.get_shop().organization)
            .filter(shop=self.get_shop())
            .publicly_bookable()
            .order_by("name")
        )


class PublicStaffListView(PublicViewMixin, generics.ListAPIView):
    """Stylists who can perform a given service, with their own duration.

    The design's screen 2 shows per-stylist durations ("Wanjiku 3 hr 30, Grace
    4 hr 15") and the handoff is explicit that these must drive availability.
    They are resolved here through the same function slice 3 will use.
    """

    throttle_scope = "staff-read"
    serializer_class = PublicStaffSerializer
    pagination_class = None

    def get_queryset(self):
        shop = self.get_shop()
        return (
            Staff.objects.for_org(shop.organization)
            .filter(shop=shop, is_active=True, is_bookable=True)
            .order_by("display_name")
        )

    def list(self, request, *args, **kwargs):
        shop = self.get_shop()
        service = get_object_or_404(
            Service.objects.for_org(shop.organization).filter(shop=shop).publicly_bookable(),
            pk=kwargs["service_id"],
        )

        links = {
            link.staff_id: link
            for link in StaffService.objects.for_org(shop.organization).filter(service=service)
        }

        rows = []
        for staff in self.get_queryset():
            try:
                minutes = _resolve(service, links.get(staff.id))
            except ServiceNotOffered:
                continue  # This stylist does not do this service; do not offer them.
            rows.append({**PublicStaffSerializer(staff).data, "duration_minutes": minutes})
        return Response(rows)


def _resolve(service, staff_service):
    from shops.durations import resolve_duration

    return resolve_duration(service=service, staff_service=staff_service)


# ------------------------------------------------------------------- the hold


class HoldCreateView(PublicViewMixin, APIView):
    """`POST /api/public/v1/shops/<slug>/holds/`

    The whole of the confirm step, and the whole of slice 5's write path. It
    creates a `pending_payment` appointment that occupies the slot against the
    exclusion constraint and expires on its own.

    Slice 6 adds one thing here and nothing else: an STK push after the hold
    exists, and a callback that confirms it. The hold, its expiry, its release
    and its countdown are all already here — which was the point of doing it
    without Daraja first.

    Every failure gets its own status code, because "you already have a slot
    held", "that time was never bookable" and "somebody beat you by 200ms" are
    three different things to say to a client mid-booking:

    - `400` the request was wrong (bad number, unbookable service)
    - `409` the slot went (`SlotUnavailable`, `SlotTaken`)
    - `429` this number is holding too much (`HoldRefused`)
    """

    throttle_scope = "hold-create"

    def post(self, request, slug):
        shop = self.get_shop()
        form = HoldRequestSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data

        service = get_object_or_404(
            Service.objects.for_org(shop.organization)
            .filter(shop=shop)
            .prefetch_related("staff_links"),
            pk=data["service"],
        )
        staff = get_object_or_404(
            Staff.objects.for_org(shop.organization).filter(
                shop=shop, is_active=True, is_bookable=True
            ),
            pk=data["staff"],
        )

        try:
            appointment = create_hold(
                shop=shop,
                service=service,
                staff=staff,
                starts_at=data["starts_at"],
                phone=data["phone"],
                client_request_id=data.get("client_request_id") or None,
            )
        except ServiceNotPubliclyBookable:
            # CLAUDE.md §5, at the API rather than only the UI. A deposit-free
            # service is absent from the public list, so this is the request
            # that did not come from the booking page.
            return Response(
                {"detail": "That service cannot be booked online. Call the shop."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ServiceNotOffered:
            return Response(
                {"detail": "That stylist does not do that service."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except HoldRefused as exc:
            body = {"detail": str(exc), "reason": exc.reason}
            response = Response(body, status=status.HTTP_429_TOO_MANY_REQUESTS)
            if exc.retry_after:
                response["Retry-After"] = str(exc.retry_after)
            return response
        except (SlotTaken, SlotUnavailable) as exc:
            # One sentence for both, two names in the logs — see booking.py.
            return Response(
                {"detail": str(exc), "reason": type(exc).__name__},
                status=status.HTTP_409_CONFLICT,
            )

        # Slice 6. The push happens *after* the hold exists, never instead of
        # it: the slot has to be genuinely gone before a client is asked for
        # money, and a push against a slot we did not manage to hold is a
        # charge for nothing.
        #
        # A refused or unavailable push is **not** an error response. The hold
        # is real, the client is about to land on the waiting screen, and the
        # payment's own state is what that screen renders — including "we could
        # not reach M-Pesa, here is *334#". Turning it into a 502 would throw
        # away a live hold the client can still pay for.
        #
        # Slice 7: a deposit fully covered by shop credit leaves nothing to
        # push, and the booking confirms without one. That is CLAUDE.md §5's
        # carve-out, not a hole in it — the credit descends from a succeeded
        # payment made from this number, and a succeeded payment *is* the phone
        # verification the deposit rule exists to provide. `create_hold` has
        # already spent the credit and written the remainder to
        # `deposit_snapshot`, so this reads one figure rather than recomputing.
        if appointment.deposit_snapshot < 1:
            confirm_credit_covered(appointment)
            appointment.refresh_from_db()
        else:
            try:
                initiate_push(appointment)
            except PushRefused as exc:
                logger.warning("stk push refused for hold %s: %s", appointment.pk, exc.reason)

        return Response(PublicHoldSerializer(appointment).data, status=status.HTTP_201_CREATED)


class HoldDetailView(PublicViewMixin, APIView):
    """`GET /api/public/v1/holds/<id>/` — what the countdown screen polls.

    The id is the session. There is no login and no token: a UUID primary key
    is unguessable, and the response contains only what the caller already sent
    plus the public service figures. Slice 1 chose UUID keys for exactly this.

    Not shop-scoped in the URL, because the client following a link from the
    confirm screen has an appointment id and no reason to also carry a slug.

    **Its own throttle scope, and a loose one.** Slice 6 made this the polled
    endpoint: the screen rewrites itself when money moved in a different app
    reaches a server the client cannot see, so it asks every three seconds for
    the life of the hold and every second past zero. That is ~180 requests for
    one booking, against a `public-read` ceiling of 240/hour shared with the
    shop, service, staff and availability reads. Two clients behind one
    carrier-grade NAT address — which is most of Safaricom — would 429 each
    other mid-payment, and a 429 here freezes the STK screen on "check your
    phone" forever. The per-phone limits in `scheduling/abuse.py` are what
    actually bound hold abuse; this reads one unguessable id and returns only
    what its holder already sent.
    """

    throttle_scope = "hold-read"

    def get(self, request, hold_id):
        return Response(PublicHoldSerializer(self.get_hold(hold_id)).data)

    def get_hold(self, hold_id):
        # `.unscoped()` for the same reason `get_shop` uses it: there is no
        # request user here. The unguessable id is the scope, and the serializer
        # is what bounds what a holder of one can read.
        return get_object_or_404(
            Appointment.objects.unscoped().select_related("staff", "service", "shop"),
            pk=hold_id,
            source=BookingSource.ONLINE,
        )


class HoldReleaseView(HoldDetailView):
    """`POST /api/public/v1/holds/<id>/release/` — the client changed their mind.

    Not counted as an abandonment by `scheduling/abuse.py`. That is deliberate:
    penalising the cancel button teaches people to close the tab instead, and a
    closed tab is the case that actually costs the shop a slot for three
    minutes.
    """

    throttle_scope = "hold-release"

    def post(self, request, hold_id):
        appointment = self.get_hold(hold_id)
        release_hold(appointment, expired=False)
        return Response(PublicHoldSerializer(appointment).data)


class HoldResendView(HoldDetailView):
    """`POST /api/public/v1/holds/<id>/resend/` — screen 5's "Resend the prompt".

    The design draws this because the STK push often does not arrive, and a
    client staring at a dark screen with no way to try again abandons the
    booking. Everything that bounds it lives in `payments/stk.resend_push`:
    a per-appointment count, a minimum interval, and the grace ceiling — which
    it cannot push out, because the ceiling is derived from a timestamp nothing
    writes.

    A refusal is a 429 with a sentence and, where it applies, a `Retry-After`.
    The client stays on the same screen either way; nothing about the hold
    changes.
    """

    throttle_scope = "stk-resend"

    def post(self, request, hold_id):
        appointment = self.get_hold(hold_id)
        try:
            resend_push(appointment)
        except PushRefused as exc:
            # `retry_after` is in the **body** as well as the header. The header
            # is the correct HTTP answer and an integrating third party will
            # read it (CLAUDE.md §1); the browser client cannot, because `fetch`
            # in a cross-origin widget sees no header it was not allowed to, and
            # `booking-core`'s transport keeps only the parsed body. A countdown
            # the client cannot render is a client that retries immediately.
            body = {"detail": str(exc), "reason": exc.reason}
            if exc.retry_after:
                body["retry_after"] = exc.retry_after
            response = Response(body, status=status.HTTP_429_TOO_MANY_REQUESTS)
            if exc.retry_after:
                response["Retry-After"] = str(exc.retry_after)
            return response
        appointment.refresh_from_db()
        return Response(PublicHoldSerializer(appointment).data)
