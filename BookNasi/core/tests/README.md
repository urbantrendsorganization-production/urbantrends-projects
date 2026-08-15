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

## The hold (slice 5)

- `scheduling/tests/test_holds.py` — the hold takes the slot and gives it back.
  Both directions are load-bearing and they fail in opposite ways. A hold that
  never releases is a slot nobody can book again — not a double-booking, but
  indistinguishable from one to the client who cannot have it, and invisible to
  the shop until somebody complains. A hold that releases *early* takes a slot
  from a client who is mid-payment, which in slice 6 becomes a refund and the
  `slotLost` support call CLAUDE.md §12 still has open.

  So release is proved from four directions: the scheduled task, the Beat sweep,
  an early resolution that revokes the task, and a task that fires before expiry
  and correctly does nothing. The file also pins the cost of the no-OTP decision
  — per-phone hold limits and the abandonment cooldown from `scheduling/abuse.py`
  — and that two clients confirming the same instant get one 201 and one clean
  409, never a 500.

The frontend half of the same slice is `web/packages/booking-core`, checked by
`npm run core:check`. It is listed here because it protects a decision rather
than an implementation: the flow's state machine lives outside React so that
slice 10's embedded widget is a build target and not a second implementation. A
`react` import in that package is that decision being reversed by accident, and
nothing else in the pipeline would notice until the widget is due.

## The rules

**They are not allowed to fail, and they are not allowed to quietly disappear.**
CI runs them by explicit path, so deleting a file fails the build with a
collection error rather than a green run over a smaller suite:

```bash
uv run pytest \
  core/tests/test_tenant_isolation.py \
  core/tests/test_org_scoped_manager_guard.py \
  core/tests/test_cors.py \
  shops/tests/test_tenant_isolation.py \
  public_api/tests/test_serializer_split.py \
  scheduling/tests/test_tenant_isolation.py \
  scheduling/tests/test_concurrency.py \
  scheduling/tests/test_cross_process_race.py \
  scheduling/tests/test_cache.py \
  scheduling/tests/test_transitions.py \
  scheduling/tests/test_walk_in.py \
  scheduling/tests/test_holds.py \
  payments/tests/test_callbacks.py \
  payments/tests/test_grace_window.py \
  payments/tests/test_stk.py \
  payments/tests/test_reconciliation.py \
  payments/tests/test_system_transition_guard.py \
  payments/tests/test_support_code.py \
  payments/tests/test_sms_never_blocks_a_callback.py
```

The payments block above was added to CI at slice 6 and this command had not
caught up; it has now. A README that quotes a command CI does not run is worse
than no README, because the next person reads it as the list.

The frontend has four of its own, run in the `frontend` CI job:

```bash
npm run core:check     # packages/booking-core/scripts/check-no-framework.mjs
npm run invariants     # web/scripts/check-invariants.mjs
npm run widget:check   # packages/widget/scripts/check-widget.mjs — slice 10
npm test               # the state machine, and what only a renderer can assert
```

CLAUDE.md §10's four invariants ship as constants in `packages/tokens`; the
tokens job proves they are not CSS custom properties, and `npm run invariants`
proves the screens actually use them. A 44 px button on the wet-hands screen is
not a styling regression, it is a mis-tap that books the wrong time — and slice
5 shipped exactly that mistake on a Back button, caught here rather than in a
salon.

`npm run core:check` refuses a framework import, a browser global or a timer
inside `booking-core`. `npm test` covers the state machine and the two things a
constant cannot check: that a 300-character service name renders whole without
collapsing the row, and that the slot grid is three per row *because the
invariant says so* rather than because someone typed 3.

If a future slice needs to change what these assert, that is a conversation, not
a commit.

## Payments (slice 6)

The five named cases and the machinery under them. These are the tests that
decide whether a client's deposit is safe, so they are named individually in CI
rather than swept up by the full run.

- `payments/tests/test_callbacks.py` — the five cases, each as its own test:
  the late callback that must still confirm, the one that becomes `slotLost`,
  the callback that never arrives (in `test_reconciliation.py`), the duplicate,
  and the callback for a booking somebody cancelled on purpose. Plus the
  hardest one: a duplicate with a **conflicting** result, which is recorded as
  a discrepancy and **never applied**. Silently applying the later verdict turns
  a confirmed booking — one the client already has an SMS about — back into an
  unconfirmed one.
- `payments/tests/test_grace_window.py` — T_grace. A hold whose STK push is
  still outstanding is not released the instant its TTL runs out. This is the
  mechanism that makes `slotLost` rare rather than routine, and the ceiling is
  derived from `hold_expires_at` rather than stored, so no code path can extend
  it. Weakening this file means manufacturing the worst state this product has.
- `payments/tests/test_stk.py` — the row is written before the Daraja call, a
  timeout is `unknown` and not `push_failed`, and a resend supersedes rather
  than duplicates. The superseded push can still be answered, which is why the
  duplicate rule is "first *result* wins" and not "first terminal state wins".
- `payments/tests/test_reconciliation.py` — we do not wait to be told what
  happened to money; we ask. A separate mechanism from the hold sweep, on its
  own schedule, because one job doing both means either a slow M-Pesa holds the
  calendar hostage or a busy calendar skips a payment.
- `payments/tests/test_system_transition_guard.py` — `pending_payment ->
  confirmed` is the edge no staff member may have, because confirming an unpaid
  hold is what a *paid callback* does. Parsed from the source, not grepped.
- `payments/tests/test_sms_never_blocks_a_callback.py` — a slow SMS gateway
  must not hold a row lock on money, because a slow 200 to Safaricom is a
  Safaricom retry, and that turns a slow third party into a payment outage.
- `payments/tests/test_support_code.py` — the code is searchable in Django
  admin **in this slice**. The owner dashboard is slice 9, and a code nobody can
  look up is decoration on the one screen where the client is already unhappy.

## Cross-origin, and the widget (slice 10)

- `core/tests/test_cors.py` — the widget runs inside somebody else's page, so
  the API has to answer cross-origin requests. Most of this file asserts
  **absences**, which is why it is here: a header that is not set leaves no
  trace in a diff, in a log, or in a review, and the CORS mistake with teeth —
  reflect the caller's origin, then allow credentials — is two lines nobody
  wrote. The complete set of headers the middleware can set is read from the
  syntax tree and pinned, so it speaks for the responses no test reaches.

  The other half is the opposite mistake. `/api/v1/` is the org-scoped surface,
  session-authenticated and same-origin, and the same-origin policy is what
  stands between a stylist's browser and a page that reads their organization's
  takings. Widening CORS to reach it would undo `core/tenancy.py` from the
  outside, so the tests assert that the admin, the callback and every
  authenticated route carry no header at all.

The frontend half is `npm run widget:check`. It is load-bearing for the same
reason `npm run core:check` is: it protects a decision. Two of its checks read
the **resolved** stylesheet and the shipped bundle rather than the TypeScript,
because `min-height: ${INVARIANTS.minTargetHeightPx}px` proves only that the
constant is referenced — not that the rule which ships says 52px. It also
refuses a browser global outside `mount.ts`, which is what keeps the eight
screens assertable without a DOM, and holds the bundle to a 20 kB gzipped
budget, which is what keeps a date library out of a 3G page.
