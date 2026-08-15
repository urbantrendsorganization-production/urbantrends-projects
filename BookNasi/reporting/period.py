"""The date range, and the comparison the dashboard is allowed to draw.

## Why there is no "before deposits" baseline

The design's headline card draws no-shows **before vs after deposits** as two
bars, 18.4 % grey against 7.1 % green. That comparison cannot be computed: the
"before" is the shop's notebook, and we were not there. Every number in this
module comes from rows we wrote ourselves, and the first of those was written on
the day the shop signed up.

Three ways to fake it were considered and all three are worse than not drawing
the card:

- **Ask the owner for their old rate.** A remembered number, entered once, that
  then appears in green next to a measured one for the life of the account. It
  would be indistinguishable on screen from something we observed.
- **Compare deposit-backed against deposit-free bookings.** Structurally rigged.
  A walk-in is recorded at the chair with the client already in it, so it can
  essentially never be a no-show, and walk-ins are the majority of Kenyan salon
  trade (CLAUDE.md §4). The deposit column would win a race the other runner
  cannot enter.
- **Ship the design's numbers as placeholders.** No.

What is left is real and is nearly as good an argument: **the shop against its
own recent past**, plus the money a forfeit actually kept. So a period always
carries the immediately preceding period of equal length, and the dashboard
labels it as what it is — last 30 days against the 30 before them, not against
a world without deposits.

## Days, not instants

A period is a pair of **EAT calendar dates, both inclusive**, because that is
what an owner means by "this month". The instants are derived at the edge with
`local_midnight`, so the boundary rule matches the availability engine's rather
than being invented here.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from scheduling.availability import local_date, local_midnight

#: The default window. Long enough that a no-show rate is not one bad Saturday,
#: short enough that a shop can see a change they made last month.
DEFAULT_DAYS = 30

#: The longest range that may be asked for in one request. A year of a busy
#: shop is a few tens of thousands of appointment rows, which is fine; ten years
#: of eight shops is a request that ties up a worker, and no owner needs it from
#: this screen.
MAX_DAYS = 366


class PeriodInvalid(ValueError):
    """Bad `?from`/`?to`. Rendered as a 400, never as a silent default — a
    dashboard that quietly substitutes a different range than the one asked for
    is a dashboard whose numbers cannot be checked."""


@dataclass(frozen=True)
class Period:
    """An inclusive span of EAT calendar dates, plus the one before it."""

    starts_on: date
    ends_on: date

    @property
    def days(self):
        return (self.ends_on - self.starts_on).days + 1

    @property
    def previous(self):
        """The equal-length span immediately before this one.

        Equal *length*, not "the same month last year": the comparison has to
        hold when a period is 7 days or 93, and a same-length neighbour is the
        only rule that does. Its weakness is worth naming — December against
        November compares a festive month to an ordinary one — which is why the
        API returns both dates and the screen prints them.
        """
        length = timedelta(days=self.days)
        return Period(self.starts_on - length, self.starts_on - timedelta(days=1))

    @property
    def utc_bounds(self):
        """`[start, end)` in UTC. Half-open, matching `time_range` everywhere
        else, so an appointment at exactly midnight belongs to one day only."""
        return local_midnight(self.starts_on), local_midnight(self.ends_on + timedelta(days=1))

    def dates(self):
        day = self.starts_on
        while day <= self.ends_on:
            yield day
            day += timedelta(days=1)

    def contains(self, moment):
        return self.starts_on <= local_date(moment) <= self.ends_on


def today_eat(now=None):
    from django.utils import timezone

    return local_date(now or timezone.now())


def parse_period(params, *, now=None):
    """`?from=YYYY-MM-DD&to=YYYY-MM-DD`, both optional, both inclusive.

    Neither given is the common case — the dashboard opens on the last
    `DEFAULT_DAYS` ending today. Giving one and not the other is accepted and
    anchored to today, because "since the 1st" is a thing an owner means.
    """
    today = today_eat(now)
    raw_from = (params.get("from") or "").strip()
    raw_to = (params.get("to") or "").strip()

    ends_on = _parse_date(raw_to, "to") if raw_to else today
    if raw_from:
        starts_on = _parse_date(raw_from, "from")
    else:
        starts_on = ends_on - timedelta(days=DEFAULT_DAYS - 1)

    if ends_on < starts_on:
        raise PeriodInvalid("The end of the range is before its start.")
    period = Period(starts_on, ends_on)
    if period.days > MAX_DAYS:
        raise PeriodInvalid(
            f"That range is {period.days} days. The most in one report is {MAX_DAYS}."
        )
    return period


def _parse_date(raw, field):
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise PeriodInvalid(f"`{field}` should look like 2026-08-14.") from exc
