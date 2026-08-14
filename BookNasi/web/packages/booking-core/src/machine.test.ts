/**
 * The flow, tested with no server, no DOM and no timers.
 *
 * That is the payoff of the reducer being pure — the same payoff the
 * availability engine's `test_derivation.py` gets, for the same reason. If
 * these ever need a fixture or a wait, the logic has leaked back into a
 * component.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ORDER,
  PAYMENT_STEPS,
  blockedReason,
  canContinue,
  canResend,
  countdownLabel,
  initialState,
  isHoldExpired,
  isPaymentStep,
  offeredSlots,
  reduce,
  secondsRemaining,
  slotIsStillHeld,
  stepFor,
  stepNumber,
} from "./machine";
import { countdown, money, refundSentence, spellDuration } from "./money";
import {
  ANYONE,
  type AnyStaffSlot,
  type Availability,
  type Hold,
  type PaymentView,
  type Service,
} from "./types";

const BRAIDS: Service = {
  id: "svc-braids",
  name: "Knotless braids, medium, waist length",
  description: "",
  duration_minutes: 240,
  price: 3500,
  deposit_mode: "percent",
  deposit_amount: 875,
  balance_due: 2625,
};

const SHAVE: Service = { ...BRAIDS, id: "svc-shave", name: "Beard trim", duration_minutes: 20 };

function slot(time: string, staff = "wanjiku"): AnyStaffSlot {
  return {
    starts_at: `2026-09-09T${time}:00Z`,
    ends_at: `2026-09-09T${time}:00Z`,
    local_time: time,
    duration_minutes: 240,
    staff_id: staff,
    staff_name: staff,
  };
}

const AVAILABILITY: Availability = {
  date: "2026-09-09",
  service_id: "svc-braids",
  any_staff: [slot("07"), slot("08", "grace")],
  by_staff: [
    { staff_id: "wanjiku", display_name: "Wanjiku", slots: [slot("07")] },
    { staff_id: "grace", display_name: "Grace", slots: [slot("08", "grace"), slot("09", "grace")] },
  ],
};

function through(...events: Parameters<typeof reduce>[1][]) {
  return events.reduce(reduce, initialState);
}

test("the steps run in the design's order", () => {
  let state = through({ type: "CHOOSE_SERVICE", service: BRAIDS });
  assert.equal(state.step, "staff");
  state = reduce(state, { type: "CHOOSE_STAFF", choice: ANYONE });
  assert.equal(state.step, "slot");
  state = reduce(state, { type: "CHOOSE_SLOT", slot: slot("07") });
  assert.equal(state.step, "confirm");
  assert.equal(stepNumber(state), 4);
});

test('"anyone available" is pre-selected the moment a service is chosen', () => {
  // The design's screen 2: first in the list and already selected.
  const state = through({ type: "CHOOSE_SERVICE", service: BRAIDS });

  assert.equal(state.staffChoice, ANYONE);
});

test("going back keeps every selection", () => {
  // The handoff is explicit. On 3G a lost selection is a re-fetch and thirty
  // seconds the client did not have.
  let state = through(
    { type: "CHOOSE_SERVICE", service: BRAIDS },
    { type: "CHOOSE_STAFF", choice: "grace" },
    { type: "AVAILABILITY_LOADED", availability: AVAILABILITY },
    { type: "CHOOSE_SLOT", slot: slot("08", "grace") }
  );

  state = reduce(state, { type: "BACK" });
  state = reduce(state, { type: "BACK" });

  assert.equal(state.step, "staff");
  assert.equal(state.service?.id, "svc-braids");
  assert.equal(state.staffChoice, "grace");
  assert.equal(state.slot?.staff_id, "grace");
});

test("changing service drops the slot derived for the old one", () => {
  let state = through(
    { type: "CHOOSE_SERVICE", service: BRAIDS },
    { type: "AVAILABILITY_LOADED", availability: AVAILABILITY },
    { type: "CHOOSE_SLOT", slot: slot("07") }
  );

  state = reduce(state, { type: "CHOOSE_SERVICE", service: SHAVE });

  assert.equal(state.slot, null);
  assert.equal(state.availability, null);
});

test("re-choosing the same service keeps everything and just moves on", () => {
  // A client tapping the already-selected card is navigating, not changing
  // their mind.
  let state = through(
    { type: "CHOOSE_SERVICE", service: BRAIDS },
    { type: "CHOOSE_STAFF", choice: "grace" }
  );
  state = reduce(state, { type: "BACK" });
  state = reduce(state, { type: "CHOOSE_SERVICE", service: BRAIDS });

  assert.equal(state.staffChoice, "grace");
  assert.equal(state.step, "staff");
});

test("changing stylist drops availability that belonged to someone else's day", () => {
  let state = through(
    { type: "CHOOSE_SERVICE", service: BRAIDS },
    { type: "AVAILABILITY_LOADED", availability: AVAILABILITY },
    { type: "CHOOSE_SLOT", slot: slot("07") }
  );

  state = reduce(state, { type: "CHOOSE_STAFF", choice: "grace" });

  assert.equal(state.availability, null);
  assert.equal(state.slot, null);
});

test('"anyone" shows the server\'s earliest-per-start list, not a merge', () => {
  // CLAUDE.md §12: earliest-available-slot, explicitly not an assignment
  // algorithm. Choosing between stylists here would make it one.
  const state = through(
    { type: "CHOOSE_SERVICE", service: BRAIDS },
    { type: "AVAILABILITY_LOADED", availability: AVAILABILITY }
  );

  assert.deepEqual(
    offeredSlots(state).map((s) => s.local_time),
    ["07", "08"]
  );
});

test("a named stylist shows only their own slots, tagged with them", () => {
  const state = through(
    { type: "CHOOSE_SERVICE", service: BRAIDS },
    { type: "CHOOSE_STAFF", choice: "grace" },
    { type: "AVAILABILITY_LOADED", availability: AVAILABILITY }
  );

  const offered = offeredSlots(state);
  assert.deepEqual(
    offered.map((s) => s.local_time),
    ["08", "09"]
  );
  assert.ok(offered.every((s) => s.staff_id === "grace"));
});

test("a stylist with no slots is an empty list, never a crash", () => {
  const state = through(
    { type: "CHOOSE_SERVICE", service: BRAIDS },
    { type: "CHOOSE_STAFF", choice: "nobody" },
    { type: "AVAILABILITY_LOADED", availability: AVAILABILITY }
  );

  assert.deepEqual(offeredSlots(state), []);
});

test("Continue says why it is disabled at every step", () => {
  // The design's rule: a disabled button's label states the reason.
  let state = initialState;
  assert.equal(blockedReason(state), "Pick a service first");

  state = reduce(state, { type: "CHOOSE_SERVICE", service: BRAIDS });
  state = reduce(state, { type: "CHOOSE_STAFF", choice: ANYONE });
  assert.equal(blockedReason(state), "Pick a time first");

  state = reduce(state, { type: "CHOOSE_SLOT", slot: slot("07") });
  assert.equal(blockedReason(state), "Enter your M-Pesa number");

  state = reduce(state, { type: "SET_PHONE", phone: "0712345678" });
  assert.equal(blockedReason(state), null);
  assert.equal(canContinue(state), true);
});

test("the phone check accepts what a Kenyan client actually types", () => {
  const state = through(
    { type: "CHOOSE_SERVICE", service: BRAIDS },
    { type: "CHOOSE_SLOT", slot: slot("07") }
  );
  for (const typed of ["0712345678", "+254712345678", "254 712 345 678", "0110123456"]) {
    assert.equal(canContinue(reduce(state, { type: "SET_PHONE", phone: typed })), true, typed);
  }
  for (const typed of ["", "07123", "0812345678", "abcdefghij"]) {
    assert.equal(canContinue(reduce(state, { type: "SET_PHONE", phone: typed })), false, typed);
  }
});

// ------------------------------------------------------------------ the hold

const HOLD: Hold = {
  id: "hold-1",
  status: "pending_payment",
  starts_at: "2026-09-09T07:00:00Z",
  ends_at: "2026-09-09T11:00:00Z",
  local_time: "10:00",
  hold_expires_at: "2026-09-09T06:03:00Z",
  seconds_remaining: 180,
  staff_name: "Wanjiku",
  service_name: "Knotless braids",
  price_kes: 3500,
  deposit_kes: 875,
  balance_kes: 2625,
  // Slice 6. Null until a push has been attempted — the moment between the
  // hold existing and the prompt being accepted is real and short.
  payment: null,
  shop_phone: "+254712000111",
};

test("the countdown is computed from the server's expiry, not a local timer", () => {
  const state = reduce(initialState, { type: "HOLD_CREATED", hold: HOLD });
  const start = Date.parse("2026-09-09T06:00:00Z");

  assert.equal(secondsRemaining(state, start), 180);
  assert.equal(secondsRemaining(state, start + 179_000), 1);
  assert.equal(secondsRemaining(state, start + 999_000), 0);
  assert.equal(isHoldExpired(state, start + 999_000), true);
});

test("a released hold returns to the slot picker with the list dropped", () => {
  // Back to the picker rather than to the start: the client still wants this
  // service with this stylist. The list goes because the slot they just gave
  // up is free again and the cached answer says otherwise.
  let state = through(
    { type: "CHOOSE_SERVICE", service: BRAIDS },
    { type: "CHOOSE_STAFF", choice: "grace" },
    { type: "AVAILABILITY_LOADED", availability: AVAILABILITY },
    { type: "CHOOSE_SLOT", slot: slot("08", "grace") },
    { type: "HOLD_CREATED", hold: HOLD }
  );

  state = reduce(state, { type: "HOLD_RELEASED" });

  assert.equal(state.step, "slot");
  assert.equal(state.hold, null);
  assert.equal(state.availability, null);
  assert.equal(state.service?.id, "svc-braids");
  assert.equal(state.staffChoice, "grace");
});

// ---------------------------------------------------------------- formatting

test("money is always KES with separators, never abbreviated", () => {
  assert.equal(money(3500), "KES 3,500");
  assert.equal(money(0), "KES 0");
  assert.equal(money(1500000), "KES 1,500,000");
});

test("durations are spelled", () => {
  assert.equal(spellDuration(20), "20 min");
  assert.equal(spellDuration(210), "3 hr 30 min");
  assert.equal(spellDuration(240), "4 hr");
});

test("the countdown never rounds up and never goes negative", () => {
  // A timer that lies is worse than no timer — it is the only reason it is
  // safe to ask a client to leave the page.
  assert.equal(countdown(180), "3:00");
  assert.equal(countdown(119), "1:59");
  assert.equal(countdown(0), "0:00");
  assert.equal(countdown(-30), "0:00");
});

test("the refund sentence survives the host relabelling 'deposit'", () => {
  // CLAUDE.md §10: translatable and relabellable, never removable.
  assert.match(refundSentence(24), /24 hours/);
  assert.match(refundSentence(24), /deposit/);
  assert.match(refundSentence(48, "reservation fee"), /reservation fee is refunded/);
});

// ------------------------------------------------------ the payment screens

/**
 * Slice 6. Every one of these asserts the same rule from a different angle:
 * **the step is derived from the payment, never set.** A renderer that could
 * choose the screen is a renderer that can tell a client their booking is paid
 * for when no money moved.
 */

function payment(over: Partial<PaymentView> = {}): PaymentView {
  return {
    state: "pushed",
    amount_kes: 875,
    support_code: "BK-4F7K2Q",
    mpesa_receipt: "",
    push_outstanding: true,
    message: "",
    slot_lost: false,
    ...over,
  };
}

test("a hold with no payment yet is the plain held screen", () => {
  assert.equal(stepFor(HOLD), "held");
});

test("a live prompt is screen 5", () => {
  assert.equal(stepFor({ ...HOLD, payment: payment() }), "pushed");
});

test("a live prompt stays on screen 5 even after the countdown reaches zero", () => {
  // The server holds the slot through a grace window for exactly this. A screen
  // that gave up here would be giving up ahead of the thing it is reporting on,
  // which is the unexplained failure CLAUDE.md §10 invariant 3 names.
  assert.equal(stepFor({ ...HOLD, payment: payment() }, true), "pushed");
});

test("a succeeded payment is screen 6", () => {
  const paid = payment({ state: "succeeded", push_outstanding: false, mpesa_receipt: "SJ42K19XQ7" });
  assert.equal(stepFor({ ...HOLD, status: "confirmed", payment: paid }), "paid");
});

test("a failure with the hold still alive is screen 7", () => {
  const failed = payment({
    state: "cancelled_by_user",
    push_outstanding: false,
    message: "You cancelled the payment on your phone.",
  });
  assert.equal(stepFor({ ...HOLD, payment: failed }), "failed");
});

test("the same failure once the hold has gone is timedOut, not screen 7", () => {
  // The reason stops mattering once there is nothing left to retry into.
  const failed = payment({
    state: "failed",
    push_outstanding: false,
    message: "There wasn't enough in the M-Pesa balance.",
  });
  assert.equal(stepFor({ ...HOLD, payment: failed }, true), "timedOut");
});

test("slot_lost outranks a succeeded payment", () => {
  // It *is* a succeeded payment — one with nowhere to sit. Screen 6 here would
  // tell a client their booking is confirmed while somebody else is in the chair.
  const lost = payment({
    state: "orphaned",
    push_outstanding: false,
    mpesa_receipt: "SJ42K19XQ7",
    slot_lost: true,
  });
  assert.equal(stepFor({ ...HOLD, status: "cancelled", payment: lost }), "slotLost");
});

test("a push Daraja refused is the failure screen, not 'check your phone'", () => {
  // The rejection came from the push call, so there is no ResultCode and
  // therefore no `message`, and `push_outstanding` is false — no prompt was
  // ever sent. Without an explicit branch this fell through to the
  // `payment ? "pushed"` default and sat the client on "Enter your M-Pesa PIN"
  // waiting for a prompt that does not exist, until the hold expired.
  const refused = payment({
    state: "push_failed",
    push_outstanding: false,
    message: "",
  });

  assert.equal(stepFor({ ...HOLD, payment: refused }), "failed");
});

test("a refused push after the timer has gone is timedOut, not failed", () => {
  const refused = payment({ state: "push_failed", push_outstanding: false, message: "" });

  assert.equal(stepFor({ ...HOLD, payment: refused }, true), "timedOut");
});

test("the reducer passes the caller's clock through to stepFor", () => {
  // `stepFor` has always taken an `expired` flag and no caller ever passed one,
  // so a hold whose timer had run out kept showing screen 7's "Nobody else can
  // take 10:00 until the timer runs out" under a clock reading 0:00 — for as
  // long as it took the server sweep to cancel the hold.
  const failed = payment({
    state: "failed",
    push_outstanding: false,
    message: "M-Pesa didn't complete the payment. Nothing was taken.",
  });
  const afterExpiry = Date.parse(HOLD.hold_expires_at) + 1_000;
  const beforeExpiry = Date.parse(HOLD.hold_expires_at) - 30_000;

  const stillRunning = reduce(initialState, {
    type: "HOLD_UPDATED",
    hold: { ...HOLD, payment: failed },
    now: beforeExpiry,
  });
  assert.equal(stillRunning.step, "failed");

  const gone = reduce(initialState, {
    type: "HOLD_UPDATED",
    hold: { ...HOLD, payment: failed },
    now: afterExpiry,
  });
  assert.equal(gone.step, "timedOut");
});

test("an outstanding push still outranks an expired timer", () => {
  // The server's grace window. `stepFor` consults `push_outstanding` before it
  // ever reaches `expired`, so passing the clock through must not start
  // contradicting invariant 3 — see `slotIsStillHeld`.
  const live = payment({ push_outstanding: true });
  const afterExpiry = Date.parse(HOLD.hold_expires_at) + 1_000;

  const state = reduce(initialState, {
    type: "HOLD_UPDATED",
    hold: { ...HOLD, payment: live },
    now: afterExpiry,
  });

  assert.equal(state.step, "pushed");
});

test("the reducer takes the step from the hold on every update", () => {
  let state = reduce(initialState, { type: "HOLD_CREATED", hold: HOLD });
  assert.equal(state.step, "held");

  state = reduce(state, { type: "HOLD_UPDATED", hold: { ...HOLD, payment: payment() } });
  assert.equal(state.step, "pushed");

  const paid = payment({ state: "succeeded", push_outstanding: false, mpesa_receipt: "SJ1" });
  state = reduce(state, {
    type: "HOLD_UPDATED",
    hold: { ...HOLD, status: "confirmed", payment: paid },
  });
  assert.equal(state.step, "paid");
});

test("BACK does nothing from a payment screen", () => {
  // The money either moved or it did not. A back arrow that appears to undo it
  // is the most expensive lie on the screen.
  const state = reduce(initialState, {
    type: "HOLD_CREATED",
    hold: { ...HOLD, payment: payment() },
  });

  assert.equal(reduce(state, { type: "BACK" }).step, "pushed");
});

test("the countdown says it is still checking rather than claiming to have expired", () => {
  // CLAUDE.md §10, invariant 3, applied to the grace window.
  const waiting = reduce(initialState, {
    type: "HOLD_CREATED",
    hold: { ...HOLD, payment: payment() },
  });
  assert.equal(countdownLabel(waiting, 95), "1:35");
  assert.equal(countdownLabel(waiting, 0), "Still checking with M-Pesa");

  const nothingPending = reduce(initialState, { type: "HOLD_CREATED", hold: HOLD });
  assert.equal(countdownLabel(nothingPending, 0), "0:00");
});

test("a hold whose timer has run out but whose push is live is still held", () => {
  const waiting = reduce(initialState, {
    type: "HOLD_CREATED",
    hold: { ...HOLD, payment: payment() },
  });
  const past = Date.parse("2026-09-09T06:09:00Z");

  assert.equal(isHoldExpired(waiting, past), true);
  assert.equal(slotIsStillHeld(waiting, past), true);
});

test("resend is offered while there is time left, and never once the money landed", () => {
  const waiting = reduce(initialState, {
    type: "HOLD_CREATED",
    hold: { ...HOLD, payment: payment() },
  });
  assert.equal(canResend(waiting, 90), true);
  assert.equal(canResend(waiting, 0), false);

  const paid = payment({ state: "succeeded", push_outstanding: false, mpesa_receipt: "SJ1" });
  const done = reduce(initialState, {
    type: "HOLD_CREATED",
    hold: { ...HOLD, status: "confirmed", payment: paid },
  });
  assert.equal(canResend(done, 90), false);
});

test("the payment steps are not in ORDER, so the header cannot count them", () => {
  // A client on the STK screen is not on step five of four.
  for (const step of PAYMENT_STEPS) {
    assert.equal(ORDER.includes(step), false, step);
    assert.equal(isPaymentStep(step), true, step);
  }
});
