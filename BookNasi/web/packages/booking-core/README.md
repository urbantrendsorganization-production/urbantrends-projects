# @booknasi/booking-core

The client booking flow, with no framework in it.

## Why this package exists

CLAUDE.md §1: one codebase serves a hosted booking page at
`shopname.booknasi.co.ke` **and** an embeddable widget inside a `/site`
template. Slice 10 builds the widget. If the flow — which step comes next, what
"anyone available" means, when Continue is allowed, what happens when the hold
expires — lives inside React components, slice 10 is a second implementation of
all of it, and the two drift on the first change to either.

So the rule for this package is short:

> **If it would have to be rewritten to render the same flow somewhere else, it
> does not belong in a component.**

The Next.js route under `web/app/book` is a shell. It subscribes to the store
here, renders what the state says, and calls actions. It makes no decisions.
`scripts/check-no-framework.mjs` fails the build if anything in `src/` imports
React, Next, or touches `window` — asserted structurally rather than trusted,
because this is the kind of boundary that erodes one convenient import at a
time.

## What is in here

| | |
|---|---|
| `types.ts` | The shapes the API returns, as the client sees them. |
| `machine.ts` | A pure reducer. `(state, event) -> state`. No I/O, no clock. |
| `transport.ts` | The one interface the flow needs, plus an HTTP implementation over an injected `fetch`. |
| `flow.ts` | The store: holds state, drives the transport, notifies subscribers. |
| `money.ts` | Formatting that must match the server's figures exactly. |

## What is deliberately *not* in here

- **Styling and layout.** Three slot chips per row is a design invariant
  (CLAUDE.md §10) and lives in `@booknasi/tokens`, applied by whatever is
  rendering. Grouping a list into rows of three is not flow logic.
- **The countdown's animation.** The store exposes `secondsRemaining`, computed
  from the server's `hold_expires_at`. How it is drawn, and the fact that it
  must always be visible, are the renderer's problem.
- **Anything that decides what is bookable.** Availability is derived on the
  server and re-derived on write. This package asks and displays; it never
  works out for itself whether 11:15 is free, because a second engine in
  TypeScript on the far side of a network boundary is exactly what slice 3 was
  built to avoid.

## The clock

`createBookingFlow` takes a `now` function. Every test in `*.test.ts` supplies
its own, which is why they run in milliseconds with no timers and no
flakiness — the same reason the availability engine takes `now` as a parameter.
