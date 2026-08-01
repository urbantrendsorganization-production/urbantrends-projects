"""How long a service takes, for a given staff member.

CLAUDE.md §3: "Service duration is per-service, overridable per staff member. A
senior stylist does in 30 min what a junior takes 50 for. If the schedule can't
express that, the calendar lies and staff stop trusting it."

**This is the one function slice 3 imports.** The availability engine calls it
once per staff-service pair; nothing else may reimplement the resolution order.
A second implementation would produce a calendar that disagrees with itself,
which is the specific failure CLAUDE.md warns about.

Resolution order, in full:

1. `StaffService.duration_override_minutes`, when set
2. `Service.duration_minutes` otherwise

A staff member who does not offer the service at all is not a duration of zero
and not a fallback to the service default — it is an error, and it raises. The
availability engine must not be able to quietly invent a slot for a stylist who
cannot do the job.
"""


class ServiceNotOffered(Exception):
    """This staff member does not offer this service.

    Raised rather than returning None so that a caller which forgets to check
    fails loudly instead of scheduling against a fabricated duration.
    """

    def __init__(self, staff=None, service=None):
        self.staff = staff
        self.service = service
        super().__init__(
            f"{getattr(staff, 'display_name', staff)} does not offer "
            f"{getattr(service, 'name', service)}"
        )


def resolve_duration(*, service, staff_service):
    """Minutes this staff member takes for this service.

    Takes the already-fetched `StaffService` row (or None) rather than doing a
    lookup, so slice 3 can prefetch a whole shop's links and call this in a loop
    without a query per slot.
    """
    if staff_service is None or not staff_service.is_offered:
        raise ServiceNotOffered(staff=getattr(staff_service, "staff", None), service=service)

    override = staff_service.duration_override_minutes
    # Explicitly `is not None`: a falsy 0 must never mean "no override", and a
    # zero-minute service is rejected at the model layer anyway.
    if override is not None:
        return override
    return service.duration_minutes
