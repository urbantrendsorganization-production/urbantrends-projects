/**
 * "What does this screen still need?", as a pure function.
 *
 * The slot picker is the one screen that has to ask for something after it is
 * already on screen. Everything else the flow loads in response to a tap:
 * choosing a service fetches the stylists, confirming creates the hold. But a
 * client arrives at the slot picker with no date chosen and no availability,
 * and something has to notice and go and get it.
 *
 * In the standalone app that is a `useEffect` inside `SlotPicker`. The widget
 * has no effects, so the equivalent is this: after every render, ask what the
 * state is missing, and do at most one thing about it.
 *
 * ## Why it is here and not in mount.ts
 *
 * Because it is a decision, and `mount.ts` is the file no test can reach. It is
 * also a decision with a loop in it: the answer to "there is no availability"
 * is "go and fetch it", and if the fetch fails the state is unchanged and the
 * answer is the same — forever, four times a second, from inside somebody
 * else's page. The `requested` key is what stops that, and a guard against an
 * infinite request loop is exactly the kind of thing that should have a test
 * rather than a comment.
 *
 * The first version of the widget set the date on the way in, before a service
 * existed, so `loadAvailability` returned early with nothing to ask about and
 * the picker sat on "Nothing free that day" for a shop with an empty diary.
 * That is the bug this module exists to have a test for.
 */

import type { BookingState } from "@booknasi/booking-core";

export type Effect =
  | { type: "chooseDate"; date: string }
  | { type: "loadAvailability" }
  | null;

/**
 * What identifies one availability request.
 *
 * Service, stylist and date, because those are the three the server derives an
 * answer from — change any one and the previous answer is about somebody
 * else's day. `CHOOSE_STAFF` and `CHOOSE_DATE` both clear `availability` in the
 * reducer for the same reason.
 */
export function availabilityKey(state: BookingState): string {
  return `${state.service?.id ?? ""}|${state.staffChoice ?? ""}|${state.date ?? ""}`;
}

/**
 * The one thing to do next, or nothing.
 *
 * `requested` is the key of the last request that was started — not finished.
 * A failed fetch is deliberately not retried here: the flow has already
 * classified it, the screen is already showing it, and a widget that retries a
 * dead network on a one-second beat is a widget that drains a phone battery
 * inside a stranger's page. The client's retry is choosing another day.
 */
export function pendingRequest(
  state: BookingState,
  today: string,
  requested: string | null,
): Effect {
  if (state.step !== "slot" || state.busy) return null;
  // No date yet: the picker opens on today, in EAT. This has to happen here
  // rather than on the way in, because availability needs the service and the
  // stylist, and neither exists until the client has been through two screens.
  if (!state.date) return { type: "chooseDate", date: today };
  if (state.availability) return null;
  if (availabilityKey(state) === requested) return null;
  return { type: "loadAvailability" };
}
