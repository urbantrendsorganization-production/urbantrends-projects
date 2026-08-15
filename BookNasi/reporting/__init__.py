"""The owner dashboard — slice 9.

CLAUDE.md §7: the staff view is the adoption bar and the owner dashboard is what
renews the subscription. This app is the second of those and is built so it can
never cost the first: it owns **no models and no migrations**, it writes
nothing, and every query it runs is an aggregate bounded by a date range. There
is no path from here that can hold a row a Saturday morning needs.

## What it reads

`Appointment`, `Payment`, `Credit` and the shop's own configuration, through
each app's org-scoped manager. Where a single-row helper already exists it is
reused rather than reimplemented — `capacity.py` constructs the availability
engine's own `StaffDayFacts` — except where the single-row version is a query
per row. `lifecycle.paid_deposit_for` is the example, and `metrics._money`
carries a note saying so.

## What this slice deliberately does not build

The design's Overview page is one of five tabs, and the other four are their own
work:

- **Appointments, Clients and Staff tabs** — list and search screens over data
  this slice only aggregates. The Clients tab in particular carries the DPA §9
  export and delete paths, which are a compliance surface rather than a report.
- **Settings** — services, deposits, hours, booking page, notifications, billing.
- **Overview variation B** and the switcher's subscription/renewal footer.
  Subscription state is a plain enum with nothing enforcing it (§12), so a
  renewal price on the switcher would be a number with no system behind it.
- **Adoption warnings** ("Thika Rd has recorded no walk-ins in 9 days") — out of
  v1 by §12. The `unresolved` count this app does publish is a different thing:
  a caveat on figures being displayed, not a nudge about behaviour.
"""
