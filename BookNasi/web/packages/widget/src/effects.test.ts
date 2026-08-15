/**
 * The slot picker's one asynchronous need, and the loop it could become.
 *
 * The bug this file exists for: the first version of the widget chose today's
 * date on the way in, before a service had been picked. `loadAvailability`
 * returns early with no service, so the request never went out, and the picker
 * sat on "Nothing free that day" for a shop with a completely empty diary. It
 * was invisible in every test, because every test asserted on a state that
 * already had availability in it.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { type BookingState, initialState } from "@booknasi/booking-core";

import { availabilityKey, pendingRequest } from "./effects";

const TODAY = "2026-08-15";

function slotStep(over: Partial<BookingState> = {}): BookingState {
  return {
    ...initialState,
    step: "slot",
    service: { id: "svc", name: "", description: "", duration_minutes: 20, price: 500,
               deposit_mode: "flat", deposit_amount: 150, balance_due: 350 },
    staffChoice: "anyone",
    ...over,
  };
}

test("arriving at the slot picker with no date opens it on today, in EAT", () => {
  // Not on the way in: availability needs a service and a stylist, and neither
  // exists until the client has been through two screens.
  assert.deepEqual(pendingRequest(slotStep(), TODAY, null), { type: "chooseDate", date: TODAY });
});

test("a date with no availability asks for it", () => {
  const effect = pendingRequest(slotStep({ date: TODAY }), TODAY, null);

  assert.deepEqual(effect, { type: "loadAvailability" });
});

test("nothing is asked for twice", () => {
  const state = slotStep({ date: TODAY });

  assert.equal(pendingRequest(state, TODAY, availabilityKey(state)), null);
});

test("a failed request is not retried on the next beat", () => {
  // The flow has classified it and the screen is already showing it. A widget
  // that retries a dead network four times a second drains a phone inside
  // somebody else's page.
  const state = slotStep({ date: TODAY, error: { kind: "offline", message: "No connection." } });

  assert.equal(pendingRequest(state, TODAY, availabilityKey(state)), null);
});

test("changing the stylist asks again, because the answer was about another day", () => {
  const first = slotStep({ date: TODAY });
  const second = slotStep({ date: TODAY, staffChoice: "wanjiku" });

  assert.deepEqual(pendingRequest(second, TODAY, availabilityKey(first)), {
    type: "loadAvailability",
  });
});

test("changing the date asks again", () => {
  const first = slotStep({ date: TODAY });
  const second = slotStep({ date: "2026-08-17" });

  assert.deepEqual(pendingRequest(second, TODAY, availabilityKey(first)), {
    type: "loadAvailability",
  });
});

test("changing the service asks again", () => {
  const first = slotStep({ date: TODAY });
  const second = slotStep({ date: TODAY, service: { ...first.service!, id: "other" } });

  assert.deepEqual(pendingRequest(second, TODAY, availabilityKey(first)), {
    type: "loadAvailability",
  });
});

test("availability already in hand needs nothing", () => {
  const state = slotStep({
    date: TODAY,
    availability: { date: TODAY, service_id: "svc", any_staff: [], by_staff: [] },
  });

  assert.equal(pendingRequest(state, TODAY, null), null);
});

test("an empty day is an answer, not a missing one", () => {
  // `any_staff: []` is the shop being full. Treating it as "not loaded yet"
  // would ask again every second for a day that has nothing on it.
  const state = slotStep({
    date: TODAY,
    availability: { date: TODAY, service_id: "svc", any_staff: [], by_staff: [] },
  });

  assert.equal(pendingRequest(state, TODAY, availabilityKey(state)), null);
});

test("a request in flight is not duplicated", () => {
  assert.equal(pendingRequest(slotStep({ date: TODAY, busy: true }), TODAY, null), null);
});

test("no other step asks for anything", () => {
  for (const step of ["service", "staff", "confirm", "held", "pushed", "paid"] as const) {
    assert.equal(pendingRequest(slotStep({ step, date: null }), TODAY, null), null, step);
  }
});
