"""Availability, the staff day, and the three-tap walk-in.

The public availability route answers "when can I book this?"; the org-scoped
ones answer "what does my day look like?" and "record this walk-in". They differ
in who is allowed to ask and which `Policy` applies, and share the derivation,
the cache and the loader. Any divergence beyond that would mean a client and a
stylist looking at different calendars.

## Every write goes through `create_appointment`

There is no second insert path in this file and no writable serializer behind
one. Slice 5's public booking flow and slice 4's walk-in are the same function
call with a different `source` and a different `Policy`, which is why slice 3
built it once. A view that assembled an `Appointment()` itself would skip the
re-derivation, the advisory lock and the snapshots in one go.

## Who sees what

One screen, two scopes. A stylist sees their own chair, because per-person
logins are what make the owner dashboard's revenue-per-staff column mean
anything (CLAUDE.md §12). An owner or manager sees the whole shop on the *same
screen* — a separate manager view would be a second implementation of the row,
the bands and the walk-in, and the working owner who cuts hair on Saturday needs
the staff screen anyway. A manager who also has a `Staff` row defaults to their
own chair and can widen with `?staff=all`, because at the chair the personal
list is the one that is faster than the notebook.
"""

from datetime import date

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.tenancy import MANAGING_ROLES, OrgScopedMixin
from public_api.views import PublicViewMixin
from scheduling import collisions
from scheduling.availability import Policy, derive_slots, is_free, local_date
from scheduling.booking import SlotTaken, SlotUnavailable, create_appointment
from scheduling.cache import facts_for_shop_day
from scheduling.dayview import appointments_for_day, top_services_for, totals_for
from scheduling.loading import staff_for_service
from scheduling.models import Appointment
from scheduling.serializers import (
    AnyStaffSlotSerializer,
    AppointmentSerializer,
    ClientDetailsSerializer,
    DayTotalsSerializer,
    OptionSerializer,
    ServiceChipSerializer,
    StaffChipSerializer,
    StaffSlotsSerializer,
    TransitionSerializer,
    WalkInSerializer,
)
from scheduling.statuses import AppointmentStatus, BookingSource
from scheduling.transitions import TransitionRefused, apply_transition, blocking_appointment_for
from shops.durations import ServiceNotOffered, resolve_duration
from shops.models import Service, Shop, Staff


def parse_date(raw):
    """`?date=YYYY-MM-DD`. Required — there is no implicit "today".

    Defaulting would make the response depend on the server's idea of now, and
    a client on a slow connection would silently get a different day than the
    one whose chip they tapped.
    """
    if not raw:
        raise ValueError("A date is required, as ?date=YYYY-MM-DD.")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("Dates look like 2026-08-14.") from exc


class AvailabilityForServiceMixin:
    """Slots for one service across a set of staff, on one EAT date."""

    def slots_by_staff(self, service, day, *, policy, only_staff=None):
        pairs = staff_for_service(service)
        if only_staff is not None:
            pairs = [(row, link) for row, link in pairs if row.id == only_staff.id]
        if not pairs:
            return []

        facts = facts_for_shop_day(service.shop, day, staff=[row for row, _ in pairs])
        out = []
        for staff_row, link in pairs:
            try:
                duration = resolve_duration(service=service, staff_service=link)
            except ServiceNotOffered:
                continue
            out.append(
                {
                    "staff_id": staff_row.id,
                    "display_name": staff_row.display_name,
                    "slots": derive_slots(
                        facts[staff_row.id],
                        duration_minutes=duration,
                        policy=policy,
                        now=self.now(),
                    ),
                }
            )
        return out

    def now(self):
        from django.utils import timezone

        return timezone.now()


class PublicAvailabilityView(PublicViewMixin, AvailabilityForServiceMixin, APIView):
    """`GET /api/public/v1/shops/<slug>/services/<id>/availability/?date=&staff=`

    A deposit-free service 404s here exactly as it is absent from the public
    service list — CLAUDE.md §5, enforced at the API rather than the UI. Without
    a payment there is no phone verification, so there is nothing to offer.

    Its own throttle scope, like every public endpoint — the rule and its
    history are in `scheduling/abuse.py`. This one is re-fetched on every date
    change and every stylist change, so it is the busiest read in the flow and
    the worst possible thing to share a budget with.
    """

    throttle_scope = "availability-read"

    def get(self, request, slug, service_id):
        shop = self.get_shop()
        service = get_object_or_404(
            Service.objects.for_org(shop.organization).filter(shop=shop).publicly_bookable(),
            pk=service_id,
        )
        try:
            day = parse_date(request.query_params.get("date"))
        except ValueError as exc:
            return Response({"date": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)

        only_staff = None
        if request.query_params.get("staff"):
            only_staff = get_object_or_404(
                Staff.objects.for_org(shop.organization).filter(
                    shop=shop, is_active=True, is_bookable=True
                ),
                pk=request.query_params["staff"],
            )

        # The public policy: minimum lead time and booking horizon both apply.
        by_staff = self.slots_by_staff(
            service, day, policy=Policy.for_public(shop), only_staff=only_staff
        )
        return Response(
            {
                "date": day.isoformat(),
                "service_id": str(service.id),
                # "Anyone available" is the earliest free start across everyone
                # who does the job — CLAUDE.md §12, an earliest-available-slot
                # rule and explicitly not an assignment algorithm. The staff
                # member who owns each start is named so the confirm step has
                # something to book against.
                "any_staff": AnyStaffSlotSerializer(_earliest_per_start(by_staff), many=True).data,
                "by_staff": StaffSlotsSerializer(by_staff, many=True).data,
            }
        )


class StaffAvailabilityView(OrgScopedMixin, AvailabilityForServiceMixin, APIView):
    """`GET /api/v1/orgs/<org>/shops/<shop>/staff/<staff>/availability/?date=&service=`

    The staff-side view of the same engine, under `Policy.for_staff()`: no lead
    time and no horizon. A walk-in starts now, and refusing it because
    `now + 30 minutes` has not arrived would make the product unusable for the
    majority of Kenyan salon trade — CLAUDE.md §4.
    """

    def get(self, request, org_id, shop_id, staff_id):
        staff_row = get_object_or_404(
            Staff.objects.for_org(self.organization).filter(shop_id=shop_id), pk=staff_id
        )
        service = get_object_or_404(
            Service.objects.for_org(self.organization).filter(shop_id=shop_id),
            pk=request.query_params.get("service"),
        )
        try:
            day = parse_date(request.query_params.get("date"))
        except ValueError as exc:
            return Response({"date": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)

        by_staff = self.slots_by_staff(
            service, day, policy=Policy.for_staff(), only_staff=staff_row
        )
        return Response(
            {
                "date": day.isoformat(),
                "service_id": str(service.id),
                "by_staff": StaffSlotsSerializer(by_staff, many=True).data,
            }
        )


# --------------------------------------------------------------- staff scope


class ShopDayMixin(OrgScopedMixin):
    """Resolves the shop, the requester's own chair, and how wide they may look."""

    @property
    def shop(self):
        if not hasattr(self, "_shop"):
            self._shop = get_object_or_404(
                Shop.objects.for_org(self.organization), pk=self.kwargs["shop_id"]
            )
        return self._shop

    @property
    def me(self):
        """This user's `Staff` row at this shop, or None for a manager who does
        not cut hair. Nullable because CLAUDE.md §12 keeps Membership and Staff
        separate on purpose — a manager has a login without being bookable."""
        if not hasattr(self, "_me"):
            self._me = (
                Staff.objects.for_org(self.organization)
                .filter(shop=self.shop, membership=self.membership, is_active=True)
                .first()
            )
        return self._me

    @property
    def can_view_shop(self):
        return self.membership.role in MANAGING_ROLES

    def staff_in_scope(self):
        """Whose appointments this request may see.

        `None` means every chair, and is only ever returned for a managing role.
        A staff member with no `Staff` row at this shop sees an empty day rather
        than the shop's — a manager's login is not a skeleton key to a list of
        clients they have no screen for.
        """
        asked = self.request.query_params.get("staff", "me")
        if asked == "all":
            if not self.can_view_shop:
                return []
            return None
        if asked not in ("me", "", None):
            row = get_object_or_404(
                Staff.objects.for_org(self.organization).filter(shop=self.shop), pk=asked
            )
            if not self.can_view_shop and (self.me is None or row.id != self.me.id):
                # 404, not 403 — slice 1's rule. A 403 confirms the stylist
                # exists, which is worth probing for.
                return []
            return [row]
        return [] if self.me is None else [self.me]

    def day_from_query(self):
        raw = self.request.query_params.get("date")
        return parse_date(raw) if raw else local_date(timezone.now())


class StaffDayView(ShopDayMixin, APIView):
    """`GET /api/v1/orgs/<org>/shops/<shop>/day/?date=&staff=`

    Today, in two queries plus the tenancy lookups. Deliberately not an
    availability call — see `scheduling/dayview.py`.
    """

    def get(self, request, org_id, shop_id):
        try:
            day = self.day_from_query()
        except ValueError as exc:
            return Response({"date": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)

        scope = self.staff_in_scope()
        appointments = appointments_for_day(self.shop, day, staff=scope)
        return Response(
            {
                "date": day.isoformat(),
                "server_time": timezone.now(),
                "shop": {"id": str(self.shop.id), "name": self.shop.name},
                "me": None
                if self.me is None
                else {"id": str(self.me.id), "display_name": self.me.display_name},
                "can_view_shop": self.can_view_shop,
                "scope": "shop" if scope is None else "staff",
                "totals": DayTotalsSerializer(totals_for(appointments)).data,
                "appointments": AppointmentSerializer(appointments, many=True).data,
            }
        )


class AppointmentDetailView(ShopDayMixin, APIView):
    """`GET /api/v1/orgs/<org>/shops/<shop>/appointments/<id>/`

    The one place a client's phone number is served, because the design's detail
    card has a call button and nothing else needs it.
    """

    def get(self, request, org_id, shop_id, appointment_id):
        appointment = self.get_appointment(appointment_id)
        return Response(AppointmentSerializer(appointment, context={"include_contact": True}).data)

    def get_appointment(self, appointment_id):
        query = (
            Appointment.objects.for_org(self.organization)
            .filter(shop=self.shop)
            .select_related("service", "client", "staff")
        )
        scope = self.staff_in_scope()
        if scope is not None:
            query = query.filter(staff__in=scope)
        return get_object_or_404(query, pk=appointment_id)


class AppointmentStatusView(AppointmentDetailView):
    """`POST .../appointments/<id>/status/` — every marking on the day view.

    One endpoint for start, finish, no-show, cancel and every undo, because they
    are one transition table (`scheduling/transitions.py`) and five endpoints
    would be five chances to disagree with it.
    """

    def post(self, request, org_id, shop_id, appointment_id):
        appointment = self.get_appointment(appointment_id)
        form = TransitionSerializer(data=request.data)
        form.is_valid(raise_exception=True)

        try:
            apply_transition(appointment, form.validated_data["status"])
        except TransitionRefused as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except SlotTaken:
            # The 11:05 / 11:07 case: no-show marked, chair given away, undo
            # refused by the exclusion constraint. Name what took it — the staff
            # member is looking at two real people.
            blocker = blocking_appointment_for(appointment)
            return Response(
                {
                    "detail": "That time is taken now.",
                    "taken_by": None if blocker is None else AppointmentSerializer(blocker).data,
                },
                status=status.HTTP_409_CONFLICT,
            )

        return Response(AppointmentSerializer(appointment, context={"include_contact": True}).data)


class AppointmentClientView(AppointmentDetailView):
    """`POST .../appointments/<id>/client/` — the name, asked after saving.

    The design is explicit that a walk-in's name and phone come *after* the row
    exists. This endpoint is what makes that possible: the appointment is
    already real and already holding the chair, and this attaches a person to it
    without the write being able to fail for want of one.
    """

    def post(self, request, org_id, shop_id, appointment_id):
        appointment = self.get_appointment(appointment_id)
        form = ClientDetailsSerializer(data=request.data)
        form.is_valid(raise_exception=True)

        from clients.models import Client

        phone = form.validated_data.get("phone", "")
        name = form.validated_data.get("full_name", "")
        if phone:
            # Org-scoped, never shop-scoped: a regular who visits two branches
            # is one person with one history — CLAUDE.md §3.
            from accounts.phone import normalize_phone

            client, created = Client.objects.for_org(self.organization).get_or_create(
                organization=self.organization,
                phone=normalize_phone(phone),
                defaults={"full_name": name},
            )
            if not created and name and not client.full_name:
                client.full_name = name
                client.save(update_fields=["full_name", "updated_at"])
        else:
            client = Client.objects.create(organization=self.organization, full_name=name, phone="")

        appointment.client = client
        appointment.save(update_fields=["client", "updated_at"])
        return Response(AppointmentSerializer(appointment, context={"include_contact": True}).data)


class WalkInOptionsView(ShopDayMixin, APIView):
    """`GET .../walk-in/options/` — everything taps 1 and 2 need, in one trip.

    One request rather than three, because this loads on a shop phone on 3G
    while somebody waits at the chair. Tap 1 gets this staff member's five
    most-recorded services plus the rest behind "Something else"; tap 2 gets
    every bookable colleague with whether they are free right now.
    """

    def get(self, request, org_id, shop_id):
        now = timezone.now()
        day = local_date(now)
        me = self.me
        if me is None:
            return Response(
                {"detail": "You do not have a chair at this shop."},
                status=status.HTTP_403_FORBIDDEN,
            )

        top = top_services_for(me)
        everyone = list(
            Staff.objects.for_org(self.organization)
            .filter(shop=self.shop, is_active=True, is_bookable=True)
            .prefetch_related("service_links")
        )
        durations = {}
        for service in top:
            link = next(
                (row for row in me.service_links.all() if row.service_id == service.id), None
            )
            try:
                durations[service.id] = resolve_duration(service=service, staff_service=link)
            except ServiceNotOffered:
                continue

        facts = facts_for_shop_day(self.shop, day, staff=everyone)
        freedom = {}
        for staff_row in everyone:
            their = facts.get(staff_row.id)
            free = their is None or is_free(
                their, starts_at=now, duration_minutes=15, buffer_minutes=0
            )
            freedom[staff_row.id] = (free, None if free else _free_from(their, now))

        return Response(
            {
                "now": now,
                # "Something else" is drawn in prose only, with no frame — see
                # the note in the response shape. The client renders `top` as
                # rows and `others` behind one more tap.
                "top_services": ServiceChipSerializer(
                    top, many=True, context={"durations": durations}
                ).data,
                "other_services": ServiceChipSerializer(
                    _other_services(self.organization, self.shop, me, exclude=top),
                    many=True,
                    context={"durations": durations},
                ).data,
                "staff": StaffChipSerializer(
                    everyone, many=True, context={"me_id": me.id, "freedom": freedom}
                ).data,
            }
        )


def _free_from(facts, now):
    """When this stylist next has an empty chair. Used for the design's "others
    show when they're free" line, so tap 2 is a decision and not a guess."""
    if facts is None:
        return None
    ends = sorted(busy.ends_at for busy in facts.busy if busy.ends_at > now)
    return ends[0] if ends else None


def _other_services(organization, shop, staff, *, exclude):
    """The "Something else" list. Drawn in prose only in the handoff, with no
    frame around it, so it ships as a plain full-width row under the five —
    nothing that competes with them for the first tap."""
    excluded = {service.id for service in exclude}
    offered = [
        link.service_id
        for link in staff.service_links.all()
        if link.is_offered and link.service_id not in excluded
    ]
    return list(
        Service.objects.for_org(organization).filter(shop=shop, is_active=True, id__in=offered)
    )


class WalkInView(ShopDayMixin, APIView):
    """`POST .../walk-in/` — tap 3.

    Never returns a validation error for an overlap. A walk-in that collides
    comes back as `409` with ranked options the engine computed, and the client
    renders the first one as a button — see `scheduling/collisions.py` for the
    ranking and why a red message above a form is the wrong answer here.
    """

    def post(self, request, org_id, shop_id):
        form = WalkInSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        now = timezone.now()

        staff_row = get_object_or_404(
            Staff.objects.for_org(self.organization).filter(shop=self.shop, is_active=True),
            pk=data["staff"],
        )
        if not self.can_view_shop and (self.me is None or staff_row.id != self.me.id):
            # A stylist records their own walk-ins and hands one over only
            # through a collision option, which the engine produced.
            if not _handover_allowed(self, staff_row):
                return Response(
                    {"detail": "You can only record a walk-in at your own chair."},
                    status=status.HTTP_403_FORBIDDEN,
                )
        service = get_object_or_404(
            Service.objects.for_org(self.organization)
            .filter(shop=self.shop, is_active=True)
            .prefetch_related("staff_links"),
            pk=data["service"],
        )

        starts_at = data.get("starts_at") or now
        try:
            appointment = create_appointment(
                staff=staff_row,
                service=service,
                starts_at=starts_at,
                source=BookingSource.WALK_IN,
                # "Waiting, not started" is `confirmed` with no `started_at`;
                # Start is `in_progress`. No seventh status — see
                # scheduling/transitions.py.
                status=AppointmentStatus.CONFIRMED
                if data.get("waiting")
                else AppointmentStatus.IN_PROGRESS,
                now=now,
                policy=Policy.for_staff(
                    allow_over_completed=data.get("allow_over_completed", False)
                ),
                duration_minutes=data.get("duration_minutes"),
                client_request_id=data.get("client_request_id") or None,
            )
        except ServiceNotOffered:
            return Response(
                {"detail": f"{staff_row.display_name} does not do that."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except (SlotUnavailable, SlotTaken):
            # Under `Policy.for_staff()` this can only be a collision: hours,
            # closures, the grid and the lead time are all advisory for staff,
            # so nothing else is left to refuse. See availability.Policy.
            duration = data.get("duration_minutes") or _duration_for(service, staff_row)
            options, in_the_way = collisions.resolve(
                staff=staff_row,
                service=service,
                starts_at=starts_at,
                duration_minutes=duration,
            )
            return Response(
                {
                    "detail": "That chair is taken.",
                    "options": OptionSerializer(options, many=True).data,
                    "blocked_until": max((busy.ends_at for busy in in_the_way), default=None),
                },
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            AppointmentSerializer(appointment, context={"include_contact": True}).data,
            status=status.HTTP_201_CREATED,
        )


def _handover_allowed(view, staff_row):
    """A stylist may push a walk-in to a colleague, because the engine offered
    it as "give it to Brian" — but only to a colleague at their own shop."""
    return view.me is not None and staff_row.shop_id == view.me.shop_id


def _duration_for(service, staff_row):
    link = next((row for row in service.staff_links.all() if row.staff_id == staff_row.id), None)
    return resolve_duration(service=service, staff_service=link)


def _earliest_per_start(by_staff):
    """One slot per distinct start time, from whoever offers it.

    Deduplicated because the client picking "anyone" should see 10:00 once, not
    once per stylist who happens to be free then. CLAUDE.md §12: this is
    earliest-available-slot and explicitly not an assignment algorithm — the
    first stylist in the list who is free at that time gets it, with no
    balancing, no rotation and no scoring.

    Each entry carries the staff member who owns it, because slice 5's confirm
    step has to book against a concrete person: `Appointment.staff` is not
    nullable and the exclusion constraint is per staff member. Without the id
    here the client would have to guess, and "anyone" would become a second
    availability query at the worst possible moment.
    """
    seen = {}
    for entry in by_staff:
        for slot in entry["slots"]:
            seen.setdefault(
                slot.starts_at,
                {
                    "starts_at": slot.starts_at,
                    "ends_at": slot.ends_at,
                    "duration_minutes": slot.duration_minutes,
                    "staff_id": entry["staff_id"],
                    "staff_name": entry["display_name"],
                },
            )
    return [seen[key] for key in sorted(seen)]
