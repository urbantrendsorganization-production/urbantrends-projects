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

export type Event =
  | { type: "SHOP_LOADED"; shop: Shop; services: Service[] }
  | { type: "CHOOSE_SERVICE"; service: Service }
  | { type: "STAFF_LOADED"; staff: StaffOption[] }
  | { type: "CHOOSE_STAFF"; choice: StaffChoice }
  | { type: "CHOOSE_DATE"; date: string }
  | { type: "AVAILABILITY_LOADED"; availability: Availability }
  | { type: "CHOOSE_SLOT"; slot: AnyStaffSlot }
  | { type: "SET_PHONE"; phone: string }
  | { type: "HOLD_CREATED"; hold: Hold }
  | { type: "HOLD_UPDATED"; hold: Hold }
  | { type: "HOLD_RELEASED" }
  | { type: "BACK" }
  | { type: "BUSY"; busy: boolean }
  | { type: "FAILED"; error: FlowError };

export const ORDER: Step[] = ["service", "staff", "slot", "confirm", "held"];

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
      return { ...state, step: "held", hold: event.hold, busy: false, error: null };

    case "HOLD_UPDATED":
      return { ...state, hold: event.hold };

    case "HOLD_RELEASED":
      // Back to the slot picker, not to the start. The client still wants this
      // service with this stylist; they want a different time, or the same one
      // again. Availability is dropped because the released slot has just
      // become free and the cached list says otherwise.
      return { ...state, step: "slot", hold: null, slot: null, availability: null, busy: false };

    case "BACK": {
      const index = ORDER.indexOf(state.step);
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
