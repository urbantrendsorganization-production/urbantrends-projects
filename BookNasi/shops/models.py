"""Shop configuration.

**This app owns configuration. Slice 3's `scheduling` app owns derivation.**
The dependency runs `scheduling -> shops` and never back: nothing here imports
the availability engine, computes a slot, or caches anything. That direction is
what makes the engine a pure function of the rows in this file, and therefore
testable without a calendar.

Two helpers here are imported by slice 3 and must not be reimplemented there:
`durations.resolve_duration` and `money.deposit_amount`.
"""

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

from accounts.phone import normalize_phone
from core.managers import OrgScopedQuerySet
from core.models import OrgDerivedModel, OrgScopedModel
from shops.durations import resolve_duration
from shops.integrity import DepositIntegrityMixin, UnguardedServiceQuerySet
from shops.money import (
    DEFAULT_DEPOSIT_PERCENT,
    DEFAULT_MIN_DEPOSIT,
    MAX_MIN_DEPOSIT,
    DepositMode,
    deposit_amount,
)
from shops.slugs import validate_shop_slug

MIN_SERVICE_MINUTES = 5
MAX_SERVICE_MINUTES = 600  # ten hours; waist-length braiding is a real all-day job


class Weekday(models.IntegerChoices):
    """Matches `datetime.date.weekday()` so slice 3 needs no translation."""

    MONDAY = 0, "Monday"
    TUESDAY = 1, "Tuesday"
    WEDNESDAY = 2, "Wednesday"
    THURSDAY = 3, "Thursday"
    FRIDAY = 4, "Friday"
    SATURDAY = 5, "Saturday"
    SUNDAY = 6, "Sunday"


class Shop(OrgScopedModel):
    """A physical location with its own booking page.

    No timezone field. CLAUDE.md §4: store UTC, render EAT, single zone, no DST,
    and explicitly no timezone abstraction layer. Every `TimeField` below is EAT
    wall-clock; slice 3 turns them into UTC instants.
    """

    name = models.CharField(max_length=120)
    # Globally unique: this is a hostname, not a per-tenant identifier.
    slug = models.SlugField(max_length=63, unique=True, validators=[validate_shop_slug])

    address = models.CharField(max_length=200, blank=True)
    area = models.CharField(max_length=80, blank=True, help_text="Neighbourhood, e.g. 'Wood Ave'")
    directions_url = models.URLField(blank=True, help_text="Opened by the client's Directions link")
    phone = models.CharField(max_length=16, blank=True)

    # Branding. The design has no photography anywhere and no BookNasi logo
    # mark, but the client booking page does show a 44px shop logo.
    logo_url = models.URLField(blank=True)
    accent_color = models.CharField(
        max_length=7,
        blank=True,
        help_text="Hex, e.g. #C2521F. Falls back to the BookNasi accent when blank.",
    )

    # Scheduling inputs. Owned here, consumed by slice 3.
    buffer_minutes = models.PositiveSmallIntegerField(
        default=10,
        validators=[MaxValueValidator(120)],
        help_text="Turnaround between appointments. Shop-wide in v1.",
    )
    slot_interval_minutes = models.PositiveSmallIntegerField(
        default=15,
        validators=[MinValueValidator(5), MaxValueValidator(60)],
        help_text="Slots land on a clock grid this many minutes apart. Slice 3, decision (a).",
    )
    min_lead_minutes = models.PositiveSmallIntegerField(
        default=30,
        validators=[MaxValueValidator(1440)],
        help_text="Public bookings must start at least this far ahead. Ignored for walk-ins.",
    )
    booking_horizon_days = models.PositiveSmallIntegerField(
        default=60,
        validators=[MinValueValidator(1), MaxValueValidator(365)],
        help_text="How far ahead the public can book. Bounds the damage one script can do.",
    )
    hold_ttl_minutes = models.PositiveSmallIntegerField(
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(30)],
        help_text="How long an unpaid slot is held while the STK push is outstanding.",
    )
    min_deposit_amount = models.PositiveIntegerField(
        default=DEFAULT_MIN_DEPOSIT,
        validators=[MinValueValidator(1), MaxValueValidator(MAX_MIN_DEPOSIT)],
        help_text="Floor for every deposit at this shop, in whole shillings.",
    )
    refund_window_hours = models.PositiveSmallIntegerField(
        default=24,
        validators=[MaxValueValidator(168)],
        help_text="Cancel earlier than this and the deposit is refundable. CLAUDE.md §12.",
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "shops"
        constraints = [
            models.CheckConstraint(condition=Q(buffer_minutes__lte=120), name="shop_buffer_sane"),
            models.CheckConstraint(
                condition=Q(hold_ttl_minutes__gte=1, hold_ttl_minutes__lte=30),
                name="shop_hold_ttl_sane",
            ),
            models.CheckConstraint(
                condition=Q(refund_window_hours__lte=168), name="shop_refund_window_sane"
            ),
            models.CheckConstraint(
                condition=Q(slot_interval_minutes__gte=5, slot_interval_minutes__lte=60),
                name="shop_slot_interval_sane",
            ),
            models.CheckConstraint(
                condition=Q(min_lead_minutes__lte=1440), name="shop_min_lead_sane"
            ),
            models.CheckConstraint(
                condition=Q(booking_horizon_days__gte=1, booking_horizon_days__lte=365),
                name="shop_booking_horizon_sane",
            ),
            models.CheckConstraint(
                condition=Q(min_deposit_amount__gte=1, min_deposit_amount__lte=MAX_MIN_DEPOSIT),
                name="shop_min_deposit_sane",
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.phone:
            self.phone = normalize_phone(self.phone)
        return super().save(*args, **kwargs)

    def is_open_on(self, day):
        """Does this shop open at all on this date?

        Config-level only: weekly hours minus dated closures. It knows nothing
        about staff, leave, appointments or buffers — that is slice 3's job, and
        slice 3 calls this as one of its inputs. A closure always wins over the
        weekly pattern.
        """
        # Reverse accessors are scoped by the parent row, so no `.unscoped()`
        # is needed or available here.
        if self.closures.filter(starts_on__lte=day, ends_on__gte=day).exists():
            return False
        return self.opening_hours.filter(weekday=day.weekday()).exists()


class OpeningHours(OrgDerivedModel):
    """One row per weekday the shop opens. No row means closed that day.

    A single interval per weekday, matching the per-day toggles the design
    draws. A shop that closes over lunch would need two rows; if that turns out
    to be real, the change is dropping the unique constraint, not a reshape.

    ## The overnight asymmetry — read before lifting the constraint below

    `opening_hours_close_after_open` refuses a shop that closes after midnight
    (21:00–01:00). Slice 3 leaned on that: because every offerable slot lies
    inside one EAT calendar date, the availability cache can partition on
    `(staff_id, EAT date)` with no overlap. See `scheduling/availability.py`,
    decision (e), and `scheduling/cache.py`'s `key_for`.

    Slice 4 then broke the symmetry from the other side. Staff writes ignore
    opening hours entirely (decision (f)), so an appointment *can already* span
    local midnight — a 23:30 walk-in is recordable today. That case is handled
    rather than prevented: `scheduling/loading.py` widens its appointment window
    by a day either side, `invalidation.on_appointment_write` drops both dates,
    and there is a test asserting an overnight span shows busy on both days.

    So the state of play is: **overnight work is recordable and visible, and
    overnight opening hours are refused.** Lifting this constraint is therefore
    not a one-line change to the constraint. It needs a `closes_next_day`
    boolean, a second window in `DayWindow`, and — the part that is easy to miss
    — a decision about what a "staff-day" means once a shift crosses midnight,
    because the cache key and the engine must keep agreeing about it. The
    machinery slice 4 added covers *stored* overnight rows; it does not make the
    grid, the window intersection or the key correct for overnight *hours*.
    """

    org_source = "shop"

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="opening_hours")
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    opens_at = models.TimeField(help_text="EAT wall-clock")
    closes_at = models.TimeField(help_text="EAT wall-clock")

    class Meta:
        db_table = "opening_hours"
        ordering = ["weekday", "opens_at"]
        constraints = [
            models.UniqueConstraint(fields=["shop", "weekday"], name="one_opening_row_per_weekday"),
            # This is the constraint the class docstring is about. It is load
            # bearing for the availability cache's partition, not merely a
            # sanity check on a form. Do not drop it without reading that note
            # and `scheduling/availability.py`'s decision (e).
            models.CheckConstraint(
                condition=Q(closes_at__gt=F("opens_at")), name="opening_hours_close_after_open"
            ),
        ]

    def __str__(self):
        return f"{self.shop.name} {Weekday(self.weekday).label} {self.opens_at}-{self.closes_at}"


class ShopClosure(OrgDerivedModel):
    """A dated exception that beats the weekly pattern.

    Public holidays, renovations, a death in the family. Without this a shop
    cannot close for a day, and a shop that cannot close for a day will be
    working around the product inside a month — taking the booking page down,
    or telling clients to ignore it.

    Overlapping closures are allowed and harmless: the union is what matters.
    """

    org_source = "shop"

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="closures")
    starts_on = models.DateField()
    ends_on = models.DateField(help_text="Inclusive")
    reason = models.CharField(max_length=120, blank=True)

    class Meta:
        db_table = "shop_closures"
        ordering = ["starts_on"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_on__gte=F("starts_on")), name="closure_ends_after_it_starts"
            ),
        ]

    def __str__(self):
        return f"{self.shop.name} closed {self.starts_on}–{self.ends_on}"

    def covers(self, day):
        return self.starts_on <= day <= self.ends_on


class Staff(OrgDerivedModel):
    """A bookable person at a shop.

    `membership` is nullable on purpose. An owner adds a stylist to the rota
    before that stylist has ever signed in — the design's staff list draws
    exactly that state ("Invited 3 Aug · hasn't signed in yet"), and it doubles
    as the adoption report. A Staff row with no membership is a person who
    exists on the schedule but cannot log in yet.
    """

    org_source = "shop"

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="staff")
    membership = models.ForeignKey(
        "orgs.Membership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_profiles",
    )
    display_name = models.CharField(max_length=80, help_text="What clients see, e.g. 'Wanjiku'")

    is_bookable = models.BooleanField(
        default=True, help_text="Appears in the client's stylist picker."
    )
    is_active = models.BooleanField(default=True, help_text="Still works here at all.")

    services = models.ManyToManyField(
        "shops.Service", through="shops.StaffService", related_name="staff"
    )

    class Meta:
        db_table = "staff"
        ordering = ["display_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["shop", "membership"],
                condition=Q(membership__isnull=False),
                name="one_staff_profile_per_membership_per_shop",
            ),
        ]

    def __str__(self):
        return f"{self.display_name} · {self.shop.name}"

    def clean(self):
        if self.membership_id and self.shop_id:
            if self.membership.organization_id != self.shop.organization_id:
                raise ValidationError(
                    {"membership": "That person belongs to a different organization."}
                )

    def duration_for(self, service):
        """Delegates to the one resolution function. See shops/durations.py."""
        link = (
            StaffService.objects.for_org(self.organization)
            .filter(staff=self, service=service)
            .select_related("service")
            .first()
        )
        return resolve_duration(service=service, staff_service=link)


class WorkingHours(OrgDerivedModel):
    """When this staff member is at the shop. A subset of opening hours in
    practice, but not enforced as one — a stylist who starts before the doors
    open is doing setup, and the engine intersects rather than validates."""

    org_source = "staff"

    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name="working_hours")
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    starts_at = models.TimeField(help_text="EAT wall-clock")
    ends_at = models.TimeField(help_text="EAT wall-clock")

    class Meta:
        db_table = "working_hours"
        ordering = ["weekday", "starts_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["staff", "weekday"], name="one_working_row_per_weekday"
            ),
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")), name="working_hours_end_after_start"
            ),
        ]

    def __str__(self):
        return f"{self.staff.display_name} {Weekday(self.weekday).label}"


class Leave(OrgDerivedModel):
    """Dated absence. Whole days in v1.

    The design says a leave block removes availability *and* notifies clients
    already booked into it. The notification is slice 8; the removal is slice 3.
    This is only the record.
    """

    org_source = "staff"

    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name="leave")
    starts_on = models.DateField()
    ends_on = models.DateField(help_text="Inclusive")
    reason = models.CharField(max_length=120, blank=True)

    class Meta:
        db_table = "staff_leave"
        ordering = ["starts_on"]
        verbose_name_plural = "leave"
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_on__gte=F("starts_on")), name="leave_ends_after_it_starts"
            ),
        ]

    def __str__(self):
        return f"{self.staff.display_name} on leave {self.starts_on}–{self.ends_on}"

    def covers(self, day):
        return self.starts_on <= day <= self.ends_on


class ServiceQuerySet(DepositIntegrityMixin, OrgScopedQuerySet):
    """Extends the org-scoped queryset so the slice 1 guard still applies, and
    carries the deposit guard so `.update()` cannot leave `deposit_amount`
    stale. See shops/integrity.py."""

    #: The rule, written once. `Service.is_publicly_bookable` mirrors it in
    #: Python, and a test asserts the two agree across every combination —
    #: because two expressions of one rule is exactly how drift starts.
    PUBLICLY_BOOKABLE = Q(is_active=True, is_publicly_listed=True, deposit_amount__gt=0)

    def publicly_bookable(self):
        return self.filter(self.PUBLICLY_BOOKABLE)


class Service(OrgDerivedModel):
    """Something a shop sells, with its own deposit rule."""

    org_source = "shop"

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="services")
    # "Knotless braids, medium, waist length" is an ordinary name, not an edge
    # case. Sized generously, wrapped in the UI, never truncated client-side.
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)

    duration_minutes = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(MIN_SERVICE_MINUTES),
            MaxValueValidator(MAX_SERVICE_MINUTES),
        ]
    )
    #: Whole shillings. See shops/money.py for why not cents and never floats.
    price = models.PositiveIntegerField(help_text="Whole shillings")

    deposit_mode = models.CharField(
        max_length=8, choices=DepositMode.choices, default=DepositMode.PERCENT
    )
    deposit_value = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        default=DEFAULT_DEPOSIT_PERCENT,
        help_text="Shillings when mode is flat, a percentage when mode is percent.",
    )
    #: Resolved by shops.money.deposit_amount on every save. Stored so the
    #: public API can filter on it in SQL and so slice 6 pushes exactly the
    #: figure the client was shown. Never write this column directly.
    deposit_amount = models.PositiveIntegerField(default=0, editable=False)

    is_active = models.BooleanField(default=True)
    is_publicly_listed = models.BooleanField(
        default=True,
        help_text="Owner's intent. Public bookability also requires a deposit — see "
        "is_publicly_bookable.",
    )

    objects = models.Manager.from_queryset(ServiceQuerySet)()
    #: Redeclared so the deposit guard covers Django's own manager too. Leaving
    #: the inherited plain `Manager` here would leave `Service.all_objects
    #: .update(price=...)` as an open bypass.
    all_objects = models.Manager.from_queryset(UnguardedServiceQuerySet)()

    class Meta:
        db_table = "services"
        # Required because this model redeclares `objects`: Django prefers a
        # manager declared on the concrete class over one inherited from an
        # abstract base, whatever the creation order. Without this line
        # `_default_manager` becomes the guarded manager again and model
        # validation, the admin and DRF's relation fields all break.
        default_manager_name = "all_objects"
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    duration_minutes__gte=MIN_SERVICE_MINUTES,
                    duration_minutes__lte=MAX_SERVICE_MINUTES,
                ),
                name="service_duration_sane",
            ),
            # No deposit mode means no value; any other mode requires one.
            models.CheckConstraint(
                condition=(
                    Q(deposit_mode=DepositMode.NONE, deposit_value__isnull=True)
                    | (~Q(deposit_mode=DepositMode.NONE) & Q(deposit_value__gt=0))
                ),
                name="service_deposit_value_matches_mode",
            ),
            models.CheckConstraint(
                condition=(~Q(deposit_mode=DepositMode.PERCENT) | Q(deposit_value__lte=100)),
                name="service_percent_deposit_within_100",
            ),
            # A flat deposit larger than the bill is a refund waiting to happen.
            models.CheckConstraint(
                condition=(~Q(deposit_mode=DepositMode.FLAT) | Q(deposit_value__lte=F("price"))),
                name="service_flat_deposit_not_above_price",
            ),
            # The database's share of keeping the *derived* column honest. It
            # catches what SQL can see without restating the money arithmetic:
            # a deposit above the bill, and a deposit on a service that has no
            # deposit rule. Percentage drift is caught by shops/integrity.py
            # instead — the rounding rule lives in exactly one place and it is
            # not here.
            models.CheckConstraint(
                condition=(
                    Q(deposit_mode=DepositMode.NONE, deposit_amount=0)
                    | Q(price=0, deposit_amount=0)
                    | (~Q(deposit_mode=DepositMode.NONE) & Q(deposit_amount__gt=0))
                )
                & Q(deposit_amount__lte=F("price")),
                name="service_deposit_amount_within_price",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if self.deposit_mode == DepositMode.NONE:
            if self.deposit_value is not None:
                raise ValidationError(
                    {"deposit_value": "Leave this empty when there is no deposit."}
                )
        else:
            if self.deposit_value is None or self.deposit_value <= 0:
                raise ValidationError({"deposit_value": "A deposit amount is required."})
            if self.deposit_mode == DepositMode.FLAT:
                if self.deposit_value != self.deposit_value.to_integral_value():
                    raise ValidationError(
                        {"deposit_value": "A flat deposit must be a whole number of shillings."}
                    )
                if self.price and self.deposit_value > self.price:
                    raise ValidationError(
                        {"deposit_value": "A deposit cannot be more than the price."}
                    )
                # A flat deposit under the shop's floor would be silently raised
                # to it by shops.money.deposit_amount, leaving the owner looking
                # at a number they did not type. Percentages are different — the
                # owner typed a rate, not an amount, so the floor applying is
                # expected and only the backstop clamp handles it.
                floor = self.shop.min_deposit_amount if self.shop_id else None
                if floor and self.price and self.deposit_value < min(floor, self.price):
                    raise ValidationError(
                        {
                            "deposit_value": f"This shop's minimum deposit is KES {floor}. "
                            "Raise the amount, or lower the shop minimum."
                        }
                    )
            elif self.deposit_mode == DepositMode.PERCENT and self.deposit_value > 100:
                raise ValidationError({"deposit_value": "A percentage cannot exceed 100."})

    def save(self, *args, **kwargs):
        # The stored column is always what the one function returns.
        # `.update()`, `.bulk_update()` and `.bulk_create()` skip this method
        # entirely; shops/integrity.py closes each of those three.
        self.deposit_amount = deposit_amount(
            mode=self.deposit_mode,
            value=self.deposit_value,
            price=self.price,
            minimum=self.shop.min_deposit_amount,
        )
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "deposit_amount" not in update_fields:
            kwargs["update_fields"] = [*update_fields, "deposit_amount"]
        return super().save(*args, **kwargs)

    @property
    def is_publicly_bookable(self):
        """Derived, never stored, so it cannot drift from the deposit rule.

        CLAUDE.md §5 and §12: a service with no deposit is not publicly
        bookable, because without a payment there is no phone verification and
        an unverified number would hold a slot for free. The owner's intent
        (`is_publicly_listed`) is necessary but not sufficient.

        Mirrors `ServiceQuerySet.PUBLICLY_BOOKABLE`; a test asserts they agree.
        """
        return bool(self.is_active and self.is_publicly_listed and self.deposit_amount > 0)


class StaffService(OrgDerivedModel):
    """Explicit join: who does what, and how long they take over it.

    An explicit row rather than a JSON blob on Staff or a denormalised column on
    Service. A blob cannot be queried, constrained or migrated; a column on
    Service cannot express two stylists with different durations, which is the
    whole point of CLAUDE.md §3.
    """

    org_source = "staff"

    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name="service_links")
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="staff_links")
    duration_override_minutes = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[
            MinValueValidator(MIN_SERVICE_MINUTES),
            MaxValueValidator(MAX_SERVICE_MINUTES),
        ],
        help_text="Blank means this staff member takes the service's own duration.",
    )
    is_offered = models.BooleanField(default=True)

    class Meta:
        db_table = "staff_services"
        constraints = [
            models.UniqueConstraint(fields=["staff", "service"], name="one_link_per_staff_service"),
            models.CheckConstraint(
                condition=(
                    Q(duration_override_minutes__isnull=True)
                    | Q(
                        duration_override_minutes__gte=MIN_SERVICE_MINUTES,
                        duration_override_minutes__lte=MAX_SERVICE_MINUTES,
                    )
                ),
                name="staff_service_override_sane",
            ),
        ]

    def __str__(self):
        return f"{self.staff.display_name} · {self.service.name}"

    def clean(self):
        if self.staff_id and self.service_id and self.staff.shop_id != self.service.shop_id:
            raise ValidationError({"service": "That service belongs to a different shop."})

    @property
    def effective_duration_minutes(self):
        """Delegates to the one resolution function. See shops/durations.py."""
        return resolve_duration(service=self.service, staff_service=self)
