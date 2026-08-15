/**
 * The store, driven by a hand-written transport.
 *
 * No server and no network: the transport is an interface precisely so these
 * can assert what the flow *does* — which call it makes, what it does with the
 * answer, how it classifies a failure — in milliseconds.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { createBookingFlow } from "./flow";
import { TransportError, type Transport } from "./transport";
import type { Availability, Hold, PaymentView, Service, Shop, StaffOption } from "./types";
import { ANYONE } from "./types";

const SHOP: Shop = {
  slug: "mint-braids",
  name: "Mint Braids",
  address: "",
  area: "Wood Ave",
  directions_url: "",
  phone: "",
  logo_url: "",
  accent_color: "",
  hold_ttl_minutes: 3,
  refund_window_hours: 24,
  deposit_credit_days: 60,
  opening_hours: [],
};

const BRAIDS: Service = {
  id: "svc-braids",
  name: "Knotless braids",
  description: "",
  duration_minutes: 240,
  price: 3500,
  deposit_mode: "percent",
  deposit_amount: 875,
  balance_due: 2625,
};

const STAFF: StaffOption[] = [
  { id: "wanjiku", display_name: "Wanjiku", duration_minutes: 210 },
  { id: "grace", display_name: "Grace", duration_minutes: 255 },
];

const AVAILABILITY: Availability = {
  date: "2026-09-09",
  service_id: "svc-braids",
  any_staff: [
    {
      starts_at: "2026-09-09T07:00:00Z",
      ends_at: "2026-09-09T10:30:00Z",
      local_time: "10:00",
      duration_minutes: 210,
      staff_id: "wanjiku",
      staff_name: "Wanjiku",
    },
  ],
  by_staff: [{ staff_id: "wanjiku", display_name: "Wanjiku", slots: [] }],
};

const HOLD: Hold = {
  id: "hold-1",
  status: "pending_payment",
  starts_at: "2026-09-09T07:00:00Z",
  ends_at: "2026-09-09T10:30:00Z",
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
  shop_name: "Mint Braids",
  refund_window_hours: 24,
  deposit_credit_days: 60,
};

/** A live prompt: accepted by Safaricom, no verdict yet. */
function pushed(over: Partial<PaymentView> = {}): PaymentView {
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

/**
 * Records every call, including overridden ones.
 *
 * The recording wraps the *merged* transport rather than living inside each
 * default. Doing it the other way round means an override silently stops being
 * recorded, and an assertion about what was called then passes because nothing
 * was — which is the shape of a test that has quietly stopped testing.
 */
function fakeTransport(overrides: Partial<Transport> = {}) {
  const calls: { name: string; args: any[] }[] = [];
  const base: Transport = {
    getShop: async () => SHOP,
    getServices: async () => [BRAIDS],
    getStaff: async () => STAFF,
    getAvailability: async () => AVAILABILITY,
    createHold: async () => HOLD,
    repointPayment: async () => ({}),
    getHold: async () => HOLD,
    releaseHold: async () => ({ ...HOLD, status: "cancelled" }),
    resendPush: async () => ({ ...HOLD, payment: pushed() }),
  };
  const merged = { ...base, ...overrides } as Record<string, (...args: any[]) => Promise<any>>;
  const recorded: Record<string, (...args: any[]) => Promise<any>> = {};
  for (const [name, method] of Object.entries(merged)) {
    recorded[name] = async (...args: any[]) => {
      calls.push({ name, args });
      return method(...args);
    };
  }
  return { transport: recorded as unknown as Transport, calls };
}

function makeFlow(overrides: Partial<Transport> = {}, now = () => Date.parse("2026-09-09T06:00:00Z")) {
  const { transport, calls } = fakeTransport(overrides);
  let counter = 0;
  const flow = createBookingFlow({
    transport,
    slug: "mint-braids",
    now,
    requestId: () => `req-${++counter}`,
  });
  return { flow, calls };
}

test("the whole happy path, from link to held slot", async () => {
  const { flow } = makeFlow();

  await flow.load();
  await flow.chooseService(BRAIDS);
  flow.chooseStaff(ANYONE);
  await flow.chooseDate("2026-09-09");
  flow.chooseSlot(flow.getState().availability!.any_staff[0]);
  flow.setPhone("0712345678");
  await flow.confirm();

  const state = flow.getState();
  assert.equal(state.step, "held");
  assert.equal(state.hold?.id, "hold-1");
  assert.equal(flow.tick(), 180);
});

test('"anyone" asks the server for everyone, and a named stylist for one', async () => {
  const { flow, calls } = makeFlow();
  await flow.load();
  await flow.chooseService(BRAIDS);

  await flow.chooseDate("2026-09-09");
  assert.equal(calls.at(-1)!.args[3], undefined, "anyone must not filter by staff");

  flow.chooseStaff("grace");
  await flow.loadAvailability();
  assert.equal(calls.at(-1)!.args[3], "grace");
});

test("confirm books against the stylist who owns the slot", async () => {
  // Not against "anyone": Appointment.staff is not nullable and the exclusion
  // constraint is per staff member. The availability response names the owner
  // so the client never has to guess.
  const { flow, calls } = makeFlow();
  await flow.load();
  await flow.chooseService(BRAIDS);
  await flow.chooseDate("2026-09-09");
  flow.chooseSlot(flow.getState().availability!.any_staff[0]);
  flow.setPhone("0712345678");

  await flow.confirm();

  const request = calls.at(-1)!.args[1];
  assert.equal(request.staff, "wanjiku");
  assert.equal(request.starts_at, "2026-09-09T07:00:00Z");
});

test("a retried confirm reuses one request id", async () => {
  // Otherwise a client on 3G who taps twice creates a second hold that
  // collides with their own first — see scheduling/booking.py.
  let attempts = 0;
  const { flow, calls } = makeFlow({
    createHold: async () => {
      attempts += 1;
      if (attempts === 1) throw new TransportError(500, {});
      return HOLD;
    },
  });
  await flow.load();
  await flow.chooseService(BRAIDS);
  await flow.chooseDate("2026-09-09");
  flow.chooseSlot(flow.getState().availability!.any_staff[0]);
  flow.setPhone("0712345678");

  await flow.confirm();
  await flow.confirm();

  const ids = calls.filter((c) => c.name === "createHold").map((c) => c.args[1].client_request_id);
  assert.equal(ids.length, 2);
  assert.equal(ids[0], ids[1]);
});

test("a lost slot is classified apart from a throttled number", async () => {
  // Three different next moves for the client: re-pick, wait, fix the number.
  // Classified here so the widget does not have to classify them again.
  for (const [status, kind] of [
    [409, "slot_taken"],
    [429, "too_many_holds"],
    [400, "bad_request"],
    [500, "server"],
  ] as const) {
    const { flow } = makeFlow({
      createHold: async () => {
        throw new TransportError(status, { detail: "no" });
      },
    });
    await flow.load();
    await flow.chooseService(BRAIDS);
    await flow.chooseDate("2026-09-09");
    flow.chooseSlot(flow.getState().availability!.any_staff[0]);
    flow.setPhone("0712345678");

    await flow.confirm();

    assert.equal(flow.getState().error?.kind, kind);
    assert.equal(flow.getState().step, "confirm", "a failed hold must not advance the flow");
  }
});

test("no connection at all reads as offline, not as a crash", async () => {
  // The booking page is opened from a WhatsApp link on 3G. This is ordinary.
  const { flow } = makeFlow({
    getShop: async () => {
      throw new TypeError("Failed to fetch");
    },
  });

  await flow.load();

  assert.equal(flow.getState().error?.kind, "offline");
});

test("a hold the server has released is noticed by the poll", async () => {
  const { flow } = makeFlow({ getHold: async () => ({ ...HOLD, status: "cancelled" }) });
  await flow.load();
  await flow.chooseService(BRAIDS);
  await flow.chooseDate("2026-09-09");
  flow.chooseSlot(flow.getState().availability!.any_staff[0]);
  flow.setPhone("0712345678");
  await flow.confirm();

  await flow.refreshHold();

  assert.equal(flow.getState().step, "slot");
  assert.equal(flow.getState().hold, null);
});

test("releasing lets the next confirm mint a fresh request id", async () => {
  // Otherwise the idempotency key would make a second, genuinely new booking
  // return the cancelled first one.
  const { flow, calls } = makeFlow();
  await flow.load();
  await flow.chooseService(BRAIDS);
  await flow.chooseDate("2026-09-09");
  flow.chooseSlot(flow.getState().availability!.any_staff[0]);
  flow.setPhone("0712345678");
  await flow.confirm();

  await flow.release();
  flow.chooseSlot(AVAILABILITY.any_staff[0]);
  await flow.confirm();

  const ids = calls.filter((c) => c.name === "createHold").map((c) => c.args[1].client_request_id);
  assert.notEqual(ids[0], ids[1]);
});

test("subscribers are told, and unsubscribing stops them being told", async () => {
  const { flow } = makeFlow();
  const seen: string[] = [];
  const stop = flow.subscribe((state) => seen.push(state.step));

  await flow.load();
  await flow.chooseService(BRAIDS);
  stop();
  flow.chooseStaff("grace");

  assert.ok(seen.includes("staff"));
  assert.ok(!seen.includes("slot"));
});

test("the store never computes availability for itself", async () => {
  // The flow asks and displays. Working out whether 11:15 is free is the
  // server's job and slice 3's engine — a second one in TypeScript on the far
  // side of a network boundary is what all of this exists to avoid.
  const { flow, calls } = makeFlow({
    getAvailability: async () => ({ ...AVAILABILITY, any_staff: [] }),
  });
  await flow.load();
  await flow.chooseService(BRAIDS);
  await flow.chooseDate("2026-09-09");

  assert.deepEqual(flow.getState().availability!.any_staff, []);
  assert.ok(calls.some((c) => c.name === "getAvailability"));
});

// ------------------------------------------------------ the payment, slice 6

test("the poll is what rewrites the screen when the money lands", async () => {
  // There is no push channel and there is not going to be one in this slice.
  // The client moved money in a different app; this is how the page finds out.
  const paid = {
    ...HOLD,
    status: "confirmed",
    payment: pushed({
      state: "succeeded",
      push_outstanding: false,
      mpesa_receipt: "SJ42K19XQ7",
    }),
  };
  const { flow } = makeFlow({
    createHold: async () => ({ ...HOLD, payment: pushed() }),
    getHold: async () => paid,
  });
  await flow.load();
  await flow.chooseService(BRAIDS);
  await flow.chooseDate("2026-09-09");
  flow.chooseSlot(AVAILABILITY.any_staff[0]);
  flow.setPhone("0712345678");
  await flow.confirm();
  assert.equal(flow.getState().step, "pushed");

  await flow.refreshHold();

  assert.equal(flow.getState().step, "paid");
  assert.equal(flow.getState().hold?.payment?.mpesa_receipt, "SJ42K19XQ7");
});

test("a cancelled hold with a payment still outstanding is NOT sent back to the picker", async () => {
  // The server holds the slot through a grace window and a late callback can
  // still confirm it. Dropping the client back to "pick a time" while their
  // money is in flight is how they end up booking twice.
  const { flow } = makeFlow({
    createHold: async () => ({ ...HOLD, payment: pushed() }),
    getHold: async () => ({ ...HOLD, status: "cancelled", payment: pushed() }),
  });
  await flow.load();
  await flow.chooseService(BRAIDS);
  await flow.chooseDate("2026-09-09");
  flow.chooseSlot(AVAILABILITY.any_staff[0]);
  flow.setPhone("0712345678");
  await flow.confirm();

  await flow.refreshHold();

  assert.notEqual(flow.getState().step, "slot");
  assert.equal(flow.getState().step, "pushed");
  assert.notEqual(flow.getState().hold, null);
});

test("a cancelled hold with no payment at all does go back to the picker", async () => {
  const { flow } = makeFlow({
    getHold: async () => ({ ...HOLD, status: "cancelled", payment: null }),
  });
  await flow.load();
  await flow.chooseService(BRAIDS);
  await flow.chooseDate("2026-09-09");
  flow.chooseSlot(AVAILABILITY.any_staff[0]);
  flow.setPhone("0712345678");
  await flow.confirm();

  await flow.refreshHold();

  assert.equal(flow.getState().step, "slot");
  assert.equal(flow.getState().hold, null);
});

test("resend asks the server and takes the hold it answers with", async () => {
  const { flow, calls } = makeFlow({
    createHold: async () => ({ ...HOLD, payment: pushed() }),
    resendPush: async () => ({ ...HOLD, payment: pushed({ support_code: "BK-SECOND" }) }),
  });
  await flow.load();
  await flow.chooseService(BRAIDS);
  await flow.chooseDate("2026-09-09");
  flow.chooseSlot(AVAILABILITY.any_staff[0]);
  flow.setPhone("0712345678");
  await flow.confirm();

  await flow.resend();

  assert.ok(calls.some((c) => c.name === "resendPush"));
  assert.equal(flow.getState().hold?.payment?.support_code, "BK-SECOND");
});

test("a refused resend comes back with how long to wait, and changes nothing else", async () => {
  // The server owns the rate, the count and the grace ceiling. A client-side
  // counter would drift from the one that actually decides.
  const { flow } = makeFlow({
    createHold: async () => ({ ...HOLD, payment: pushed() }),
    resendPush: async () => {
      throw new TransportError(429, { detail: "Give it 20 more seconds.", retry_after: 20 });
    },
  });
  await flow.load();
  await flow.chooseService(BRAIDS);
  await flow.chooseDate("2026-09-09");
  flow.chooseSlot(AVAILABILITY.any_staff[0]);
  flow.setPhone("0712345678");
  await flow.confirm();

  await flow.resend();

  const state = flow.getState();
  assert.equal(state.error?.kind, "too_many_holds");
  assert.equal(state.error?.retryAfter, 20);
  // Still on screen 5 with the original prompt. A refusal to send a *second*
  // prompt is not a failure of the first one.
  assert.equal(state.step, "pushed");
  assert.equal(state.hold?.payment?.support_code, "BK-4F7K2Q");
});

test("resend is not attempted at all when there is no hold", async () => {
  const { flow, calls } = makeFlow();

  assert.equal(await flow.resend(), null);
  assert.ok(!calls.some((c) => c.name === "resendPush"));
});
