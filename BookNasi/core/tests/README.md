# Load-bearing tests

Most tests in this repo protect an implementation. A few protect a **decision**,
and they are marked `@pytest.mark.loadbearing`.

## Tenancy (slice 1)

- `core/tests/test_tenant_isolation.py` — a user must never read another
  organization's data, and must get **404 rather than 403** when they try.
- `core/tests/test_org_scoped_manager_guard.py` — an org-scoped queryset must
  refuse to execute unless someone named an org.
- `shops/tests/test_tenant_isolation.py`,
  `scheduling/tests/test_tenant_isolation.py` — the same rule re-asserted for
  every endpoint each slice adds, because the guard covers the model layer and
  not the URL layer.

These exist because the failure they catch is silent. A cross-tenant read does
not raise, does not log, and does not look wrong in a response body — it returns
rows, and they are somebody else's. By the time anyone notices, it is a Kenya
DPA 2019 incident (CLAUDE.md §9), not a bug report.

## The public/private split (slice 2)

- `public_api/tests/test_serializer_split.py` — the unauthenticated surface's
  exact field set. A new column reaches the public API only when somebody writes
  a line, never because a parent serializer changed.

## Double-booking (slice 3)

- `scheduling/tests/test_concurrency.py` — real threads, real connections. Two
  simultaneous confirms on one slot; exactly one wins and the loser raises
  `SlotTaken` specifically.
- `scheduling/tests/test_cross_process_race.py` — the same race across two
  spawned processes, which is what production actually is. This is the strongest
  available evidence that the guarantee comes from the exclusion constraint and
  not from anything in this codebase.
- `scheduling/tests/test_cache.py` — the availability cache is a pure
  optimisation. Flush Redis mid-run and the answers must be identical. If this
  ever needs weakening, the cache has become a source of truth and a Redis
  eviction has become a double-booking.

CLAUDE.md §4 is explicit that the constraint stays "regardless of what else you
add". These are how that stays true after the next person touches it.

## Walk-ins and the day (slice 4)

- `scheduling/tests/test_walk_in.py` — the walk-in path through the same
  constraint. Three decisions: a collision comes back as **ranked options the
  engine computed**, never a validation error above a form; there is exactly one
  insert path, asserted structurally with `ast` because "no second path" is not
  something a behavioural test can see; and the offline retry is idempotent, so
  a stylist is never told that their own walk-in took their slot.
- `scheduling/tests/test_transitions.py` — every staff marking is reversible,
  and no reversal is guaranteed. No-show frees the chair on purpose, so undoing
  it two minutes later re-enters the exclusion constraint and can lose. That
  refusal must arrive as `SlotTaken` naming what took the slot, because the
  staff member is looking at two real people.

Both exist because the failure they catch is a slow one. A walk-in flow that
grows a fourth tap, or a no-show that needs an owner to undo, does not break
anything — staff simply stop using the screen, the calendar drifts from the
shop, and the subscription churns three weeks later for reasons nobody can
point at. CLAUDE.md §4 and §7 name that failure; these are what make it a red
build instead.

## The rules

**They are not allowed to fail, and they are not allowed to quietly disappear.**
CI runs them by explicit path, so deleting a file fails the build with a
collection error rather than a green run over a smaller suite:

```bash
uv run pytest \
  core/tests/test_tenant_isolation.py \
  core/tests/test_org_scoped_manager_guard.py \
  shops/tests/test_tenant_isolation.py \
  public_api/tests/test_serializer_split.py \
  scheduling/tests/test_tenant_isolation.py \
  scheduling/tests/test_concurrency.py \
  scheduling/tests/test_cross_process_race.py \
  scheduling/tests/test_cache.py \
  scheduling/tests/test_transitions.py \
  scheduling/tests/test_walk_in.py
```

The frontend has one of its own, run in the `frontend` CI job:

```bash
npm run invariants   # web/scripts/check-invariants.mjs
```

CLAUDE.md §10's four invariants ship as constants in `packages/tokens`; the
tokens job proves they are not CSS custom properties, and this proves the staff
screens actually use them. A 44 px button on the wet-hands screen is not a
styling regression, it is a mis-tap that books the wrong time.

If a future slice needs to change what these assert, that is a conversation, not
a commit.
