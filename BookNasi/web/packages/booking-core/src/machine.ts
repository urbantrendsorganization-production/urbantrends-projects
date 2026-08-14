/**
 * The flow, as a pure reducer. `(state, event) -> state`.
 *
 * No I/O, no clock, no framework. Everything that decides *what the client is
 * looking at* is here, which is what makes slice 10's widget a second renderer
 * rather than a second implementation.
 *
 * ## The machine
 *
 *     service -> staff -> slot -> confirm -> held
 *
 * matching the handoff's `browsing → serviceChosen → staffChosen → slotChosen →
 * detailsEntered → holdCreated(ttl)`. `detailsEntered` is not a step of its own
 * here: the only detail is a phone number and it lives on the confirm screen,
 * which is where the design puts it.
 *
 * ## Going back keeps everything
 *
 * The handoff is explicit: "the back arrow returns to the previous step with
 * all selections intact". So `BACK` moves `step` and touches nothing else. A
 * client who taps back to change stylist and then forward again must not find
 * their slot gone — on a 3G connection that is a re-fetch and thirty seconds
 * they did not have.
 *
 * The one exception is `CHOOSE_SERVICE`, which clears the staff and slot
 * choices, because a different service has different durations, a different
 * set of stylists who offer it, and therefore a different set of free times.
 * Keeping a slot across that change would be keeping one that was derived for
 * something else.
 *
 * ## Slice 6: the payment screens are derived, not entered
 *
 *     held -> pushed -> paid | failed | timedOut | slotLost
 *
 * There is no `SHOW_PAID` event and there is deliberately never going to be
 * one. Every one of those five screens is a function of the `payment` object
 * the server put on the hold — see `stepFor` — because the alternative is a
 * renderer that can put a client on the paid screen when no money moved. The
 * server owns two state machines here (the appointment's and the payment's)
 * and this one owns none of them; it reads.
 *
 * The one nuance is `timedOut` versus `pushed`. A countdown reaching 0:00 does
 * **not** mean the slot is gone: the server holds a hold whose STK push is
 * still outstanding for a grace window past its TTL. So while
 * `payment.push_outstanding` is true the screen stays on `pushed` and says it
 * is still checking with M-Pesa, whatever the timer says. A timer that reaches
 * zero and declares failure while the server is still holding the slot is the
 * unexplained failure CLAUDE.md §10 invariant 3 exists to prevent.
 */

import type {
  AnyStaffSlot,
  Availability,
  BookingState,
  FlowError,
  Hold,
  Service,
  Shop,
  StaffChoice,
  StaffOption,
  Step,
} from "./types";
import { ANYONE } from "./types";
import { countdown } from "./money";

export type Event =
  | { type: "SHOP_LOADED"; shop: Shop; services: Service[] }
  | { type: "CHOOSE_SERVICE"; service: Service }
  | { type: "STAFF_LOADED"; staff: StaffOption[] }
  | { type: "CHOOSE_STAFF"; choice: StaffChoice }
  | { type: "CHOOSE_DATE"; date: string }
  | { type: "AVAILABILITY_LOADED"; availability: Availability }
  | { type: "CHOOSE_SLOT"; slot: AnyStaffSlot }
  | { type: "SET_PHONE"; phone: string }
  // `now` carries the caller's clock through to `stepFor`, which takes an
  // `expired` flag it was never actually given. See `holdExpired` below.
  | { type: "HOLD_CREATED"; hold: Hold; now?: number }
  | { type: "HOLD_UPDATED"; hold: Hold; now?: number }
  | { type: "HOLD_RELEASED" }
  | { type: "BACK" }
  | { type: "BUSY"; busy: boolean }
  | { type: "FAILED"; error: FlowError };

export const ORDER: Step[] = ["service", "staff", "slot", "confirm", "held"];

/**
 * The payment screens. Not in `ORDER`, because `BACK` must not walk into them
 * and the header's `n / 4` must not count them — a client on the STK screen is
 * not on step five of four, they are waiting for a phone prompt.
 */
export const PAYMENT_STEPS: Step[] = ["pushed", "paid", "failed", "timedOut", "slotLost"];

export const initialState: BookingState = {
  step: "service",
  shop: null,
  services: [],
  service: null,
  staffOptions: [],
  staffChoice: null,
  date: null,
  availability: null,
  slot: null,
  phone: "",
  busy: false,
  hold: null,
  error: null,
};

export function reduce(state: BookingState, event: Event): BookingState {
  switch (event.type) {
    case "SHOP_LOADED":
      return { ...state, shop: event.shop, services: event.services, error: null };

    case "CHOOSE_SERVICE":
      if (state.service?.id === event.service.id) {
        return { ...state, step: "staff", error: null };
      }
      return {
        ...state,
        step: "staff",
        service: event.service,
        // A different service means different durations and a different set of
        // stylists, so anything derived from the old one is stale by
        // definition. See the module docstring.
        staffOptions: [],
        // "Anyone available" is first and pre-selected — the design's screen 2.
        staffChoice: ANYONE,
        availability: null,
        slot: null,
        error: null,
      };

    case "STAFF_LOADED":
      return { ...state, staffOptions: event.staff };

    case "CHOOSE_STAFF":
      if (state.staffChoice === event.choice) {
        return { ...state, step: "slot", error: null };
      }
      return {
        ...state,
        step: "slot",
        staffChoice: event.choice,
        // Availability is per stylist. Keeping the old list would offer times
        // that belong to somebody else's day.
        availability: null,
        slot: null,
        error: null,
      };

    case "CHOOSE_DATE":
      if (state.date === event.date) return state;
      return { ...state, date: event.date, availability: null, slot: null, error: null };

    case "AVAILABILITY_LOADED":
      return { ...state, availability: event.availability, error: null };

    case "CHOOSE_SLOT":
      return { ...state, step: "confirm", slot: event.slot, error: null };

    case "SET_PHONE":
      return { ...state, phone: event.phone, error: null };

    case "HOLD_CREATED":
      return {
        ...state,
        step: stepFor(event.hold, holdExpired(event.hold, event.now)),
        hold: event.hold,
        busy: false,
        error: null,
      };

    case "HOLD_UPDATED":
      // The step comes from the hold, every time. This is the poll's whole job:
      // the client is watching a screen that rewrites itself from the server's
      // opinion of their money, and there is no other way for it to change.
      return {
        ...state,
        step: stepFor(event.hold, holdExpired(event.hold, event.now)),
        hold: event.hold,
      };

    case "HOLD_RELEASED":
      // Back to the slot picker, not to the start. The client still wants this
      // service with this stylist; they want a different time, or the same one
      // again. Availability is dropped because the released slot has just
      // become free and the cached list says otherwise.
      return { ...state, step: "slot", hold: null, slot: null, availability: null, busy: false };

    case "BACK": {
      const index = ORDER.indexOf(state.step);
      // -1 for a payment step. There is no back from a phone prompt: the money
      // either moved or it did not, and a back arrow that appears to undo it
      // would be the most expensive lie on the screen.
      if (index <= 0) return state;
      // Everything else is left exactly as it is — see the module docstring.
      return { ...state, step: ORDER[index - 1], error: null };
    }

    case "BUSY":
      return { ...state, busy: event.busy };

    case "FAILED":
      return { ...state, busy: false, error: event.error };

    default:
      return state;
  }
}

// ------------------------------------------------------- the payment screens

/**
 * Which of the five payment screens this hold is on. **The only writer of a
 * payment step.**
 *
 * Read top to bottom; the order is the priority order and each line is a
 * decision that was made deliberately:
 *
 * 1. **`slot_lost` first.** It outranks everything, including a succeeded
 *    payment, because it *is* a succeeded payment — one with nowhere to sit.
 *    Showing screen 6 here would tell a client their booking is confirmed
 *    while somebody else is in the chair.
 * 2. **`succeeded` and the appointment confirmed** is screen 6.
 * 3. **A live push** is screen 5, whatever the countdown says. `push_outstanding`
 *    beats the clock — see the module docstring.
 * 4. **A resolved failure** is screen 7, but only while the hold is still worth
 *    retrying into. Once the slot has gone the reason no longer matters.
 * 5. **Anything else with no hold left** is `timedOut`.
 *
 * `expired` is passed in rather than computed here so the caller's clock stays
 * the single source of "now" — the same rule the availability engine follows.
 */
/**
 * Whether this hold's timer has run out, by the caller's clock.
 *
 * `stepFor` has always taken an `expired` flag and no caller ever passed one,
 * so its fifth priority rule only fired once the *server* had got round to
 * cancelling the hold — up to a sweep interval later. In that gap a failed
 * payment kept screen 7's "Nobody else can take 10:00 until the timer runs
 * out" under a clock reading 0:00.
 *
 * Grace is deliberately not applied here. `slotIsStillHeld` is the function
 * that knows an outstanding push extends the hold past its timer, and
 * `stepFor` consults `push_outstanding` before it ever reaches `expired`.
 */
export function holdExpired(hold: Hold, now = Date.now()): boolean {
  return Date.parse(hold.hold_expires_at) <= now;
}

export function stepFor(hold: Hold, expired = false): Step {
  const payment = hold.payment;

  if (payment?.slot_lost) return "slotLost";
  if (payment?.state === "succeeded" || hold.status === "confirmed") return "paid";

  // A prompt that may still be answered keeps the client on screen 5. The
  // server holds the slot through a grace window for exactly this, so a screen
  // that gave up here would be giving up ahead of the thing it is reporting on.
  if (payment?.push_outstanding) return "pushed";

  const gone = expired || hold.status === "cancelled";

  // A push Daraja refused synchronously never reached the client's phone, so
  // there is no prompt to wait for. It carries no `result_code`, which means no
  // `message`, so without this branch it fell all the way through to the
  // `payment ? "pushed"` default and sat the client on "Check your phone ·
  // Enter your M-Pesa PIN" until the hold expired. Screen 7 is the honest
  // screen: it names the failure and offers the *334# fallback.
  if (payment?.state === "push_failed") return gone ? "timedOut" : "failed";

  if (payment && payment.message) return gone ? "timedOut" : "failed";
  if (gone) return "timedOut";
  return payment ? "pushed" : "held";
}

/** True on the five screens where the booking flow is over or waiting. */
export function isPaymentStep(step: Step): boolean {
  return PAYMENT_STEPS.includes(step);
}

/**
 * What the countdown says. Not a number — the honest answer is sometimes a
 * sentence.
 *
 * CLAUDE.md §10, invariant 3: the countdown is the only reason it is safe to
 * ask a client to leave the page and open their M-Pesa PIN prompt. A timer that
 * hits 0:00 and says "expired" while the server is still holding the slot turns
 * a three-minute hold into an unexplained failure, which is the exact failure
 * the invariant names.
 */
export function countdownLabel(state: BookingState, seconds: number): string {
  const outstanding = state.hold?.payment?.push_outstanding ?? false;
  if (seconds > 0) return countdown(seconds);
  if (outstanding) return "Still checking with M-Pesa";
  return "0:00";
}

/** Whether a resend may be offered. The server refuses past its own ceiling;
 *  this only decides whether to draw the button. */
export function canResend(state: BookingState, seconds: number): boolean {
  if (state.busy) return false;
  const payment = state.hold?.payment;
  if (!payment) return false;
  if (state.step === "paid" || state.step === "slotLost" || state.step === "timedOut") {
    return false;
  }
  return seconds > 0;
}

// --------------------------------------------------------------- selectors
//
// Questions the renderer asks. Here rather than in a component so that the
// widget asks them the same way, and so that "when is Continue allowed" has
// one answer with a test on it.

/** The slots to draw, honouring the "anyone available" rule. */
export function offeredSlots(state: BookingState): AnyStaffSlot[] {
  const availability = state.availability;
  if (!availability) return [];
  if (state.staffChoice === ANYONE || state.staffChoice === null) {
    // Earliest-available-slot, computed by the server. CLAUDE.md §12 is
    // explicit that this is not an assignment algorithm, and it would become
    // one the moment this function started choosing between stylists.
    return availability.any_staff;
  }
  const entry = availability.by_staff.find((row) => row.staff_id === state.staffChoice);
  if (!entry) return [];
  return entry.slots.map((slot) => ({
    ...slot,
    staff_id: entry.staff_id,
    staff_name: entry.display_name,
  }));
}

export function canContinue(state: BookingState): boolean {
  switch (state.step) {
    case "service":
      return state.service !== null;
    case "staff":
      return state.staffChoice !== null;
    case "slot":
      return state.slot !== null;
    case "confirm":
      return state.slot !== null && isPlausiblePhone(state.phone) && !state.busy;
    default:
      return false;
  }
}

/**
 * Why Continue is disabled, for the label.
 *
 * The design is explicit that a disabled button's label says why rather than
 * greying out silently — "Pick a time first", not a dead rectangle.
 */
export function blockedReason(state: BookingState): string | null {
  if (canContinue(state)) return null;
  switch (state.step) {
    case "service":
      return "Pick a service first";
    case "staff":
      return "Pick a stylist first";
    case "slot":
      return "Pick a time first";
    case "confirm":
      return state.busy ? "Holding your slot…" : "Enter your M-Pesa number";
    default:
      return null;
  }
}

/**
 * Loose on purpose. The server normalises and validates properly — this only
 * decides when the button turns on, and a client who has typed nine digits
 * should not be told their number is wrong before they have finished.
 */
export function isPlausiblePhone(raw: string): boolean {
  const digits = raw.replace(/\D/g, "");
  return /(^0?[71]\d{8}$)|(^254[71]\d{8}$)/.test(digits);
}

/** `1 / 4` in the design's header. `held` is not a numbered step. */
export function stepNumber(state: BookingState): number {
  return Math.min(ORDER.indexOf(state.step) + 1, 4);
}

export function secondsRemaining(state: BookingState, now: number): number {
  if (!state.hold) return 0;
  const expires = Date.parse(state.hold.hold_expires_at);
  return Math.max(0, Math.floor((expires - now) / 1000));
}

export function isHoldExpired(state: BookingState, now: number): boolean {
  return state.hold !== null && secondsRemaining(state, now) === 0;
}

/**
 * Whether the client should still be told the slot is theirs.
 *
 * Deliberately not `!isHoldExpired`. The server's grace window means a hold
 * whose timer has run out but whose push is still outstanding is *still held*,
 * and this is the function that keeps the screen from contradicting it.
 */
export function slotIsStillHeld(state: BookingState, now: number): boolean {
  if (!state.hold) return false;
  if (state.hold.status === "cancelled") return false;
  if (secondsRemaining(state, now) > 0) return true;
  return state.hold.payment?.push_outstanding ?? false;
}
