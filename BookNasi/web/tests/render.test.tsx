/**
 * Rendering assertions that only a renderer can make.
 *
 * `node --test` plus `react-dom/server`. No jsdom, no test-runner dependency,
 * no transform pipeline — the TypeScript is compiled by `tsc` first and Node 22
 * runs the result. The point is to keep the two things a token file cannot
 * check honest: that the invariants reach the markup, and that a long service
 * name does not collapse a row.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { INVARIANTS } from "@booknasi/tokens";
import { renderToStaticMarkup } from "react-dom/server";

import { ServiceCard, SlotGrid } from "../components/booking/BookingFlow";
import type { AnyStaffSlot, Service } from "@booknasi/booking-core";

/**
 * 300 characters. Not a contrived string: shops write
 * "Knotless braids, medium, waist length, with beads, wash and treatment
 * included, please come with clean dry hair" and then keep going.
 */
const VERY_LONG_NAME =
  "Knotless braids, medium, waist length, with beads, wash and deep-conditioning " +
  "treatment included, please arrive with clean dry hair and allow extra time if " +
  "you are adding colour or extensions, prices vary by length and thickness, ask " +
  "us about the student discount on weekday mornings before eleven o'clock okay";

const SERVICE: Service = {
  id: "svc-1",
  name: VERY_LONG_NAME,
  description: "",
  duration_minutes: 240,
  price: 3500,
  deposit_mode: "percent",
  deposit_amount: 875,
  balance_due: 2625,
};

/**
 * React escapes `'` and `&` into entities, correctly. Un-escaping before the
 * comparison keeps the fixture a realistic service name — apostrophes and all —
 * rather than one trimmed to suit the assertion.
 */
function readable(html: string): string {
  return html
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&");
}

function slot(time: string): AnyStaffSlot {
  return {
    starts_at: `2026-09-09T0${time.slice(0, 1)}:00:00Z`,
    ends_at: `2026-09-09T0${time.slice(0, 1)}:30:00Z`,
    local_time: time,
    duration_minutes: 30,
    staff_id: "wanjiku",
    staff_name: "Wanjiku",
  };
}

test("a 300-character service name renders whole and never truncated", () => {
  assert.ok(VERY_LONG_NAME.length >= 300, `fixture is only ${VERY_LONG_NAME.length} chars`);

  const html = renderToStaticMarkup(
    <ServiceCard service={SERVICE} selected={false} onChoose={() => {}} />
  );

  // Present in full. The design's rule is that long names wrap to two lines and
  // are never truncated client-side — an ellipsis here would hide which of two
  // similar services the client is about to book.
  assert.ok(readable(html).includes(VERY_LONG_NAME.slice(0, 80)));
  assert.ok(readable(html).includes(VERY_LONG_NAME.slice(-40)));
  assert.ok(!/text-overflow:\s*ellipsis/.test(html));
  assert.ok(!/white-space:\s*nowrap/.test(html));
});

test("the long name does not push the price out of the row", () => {
  // The two properties that actually prevent the collapse. A flex child
  // defaults to `min-width: auto`, so without these the name refuses to shrink
  // and the price is pushed off the card.
  const html = renderToStaticMarkup(
    <ServiceCard service={SERVICE} selected={false} onChoose={() => {}} />
  );

  assert.match(html, /min-width:\s*0/);
  assert.match(html, /overflow-wrap:\s*anywhere/);
  assert.ok(html.includes("KES 3,500"));
  assert.ok(html.includes("KES 875 deposit"));
});

test("the card still meets the 52px target with a name that long", () => {
  const html = renderToStaticMarkup(
    <ServiceCard service={SERVICE} selected={false} onChoose={() => {}} />
  );

  assert.match(html, new RegExp(`min-height:\\s*${INVARIANTS.minTargetHeightPx}px`));
});

test("the slot grid is three per row, from the invariant and not a literal", () => {
  // CLAUDE.md §10, invariant 2. Denser grids raise mis-taps on the one screen
  // where a mis-tap books the wrong time.
  const slots = ["09:00", "09:15", "09:30", "09:45", "10:00"].map(slot);

  const html = renderToStaticMarkup(<SlotGrid slots={slots} chosen={null} onChoose={() => {}} />);

  assert.equal(INVARIANTS.slotsPerRow, 3);
  assert.match(html, /grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)/);
});

test("slot chips are mono with tabular figures and meet the target height", () => {
  const html = renderToStaticMarkup(
    <SlotGrid slots={[slot("09:00")]} chosen={null} onChoose={() => {}} />
  );

  assert.match(html, new RegExp(`min-height:\\s*${INVARIANTS.minTargetHeightPx}px`));
  assert.match(html, /font-variant-numeric:\s*tabular-nums/);
});

test("slots split into morning and afternoon, as the design groups them", () => {
  const html = renderToStaticMarkup(
    <SlotGrid slots={[slot("09:00"), slot("14:00")].map((s) => s)} chosen={null} onChoose={() => {}} />
  );

  assert.ok(html.includes("Morning"));
  assert.ok(html.includes("Afternoon"));
});

// ------------------------------------------------ screens 5–8, slice 6
//
// The four things these assert are the ones a token file cannot see and a
// state-machine test cannot reach: that invariants 3 and 4 arrive in the
// markup, and that three specific pieces of copy the design drew are **not**
// there. Each of those three was removed for a stated reason, and a reason
// that only lives in a commit message is a reason that gets reverted.

import { Failed, Paid, Pushed, SlotLost } from "../components/booking/BookingFlow";
import type { BookingState, Hold, PaymentView } from "@booknasi/booking-core";

function paymentView(over: Partial<PaymentView> = {}): PaymentView {
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

function holdWith(payment: PaymentView | null, over: Partial<Hold> = {}): Hold {
  return {
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
    payment,
    shop_phone: "+254712000111",
    shop_name: "Mint Braids",
    refund_window_hours: 24,
    deposit_credit_days: 60,
    ...over,
  };
}

function stateWith(hold: Hold, step: BookingState["step"]): BookingState {
  return {
    step,
    shop: null,
    services: [],
    service: null,
    staffOptions: [],
    staffChoice: null,
    date: null,
    availability: null,
    slot: null,
    phone: "0712345678",
    hold,
    busy: false,
    error: null,
  };
}

const noopFlow = { resend: async () => null, release: async () => null } as any;

test("the STK waiting screen carries the *334# fallback, from the token", () => {
  // CLAUDE.md §10, invariant 4. When the push does not arrive — and it often
  // does not — this line is the difference between a completed deposit and an
  // abandoned booking. It is never behind a tap.
  const html = renderToStaticMarkup(
    <Pushed state={stateWith(holdWith(paymentView()), "pushed")} flow={noopFlow} seconds={140} />
  );

  assert.ok(html.includes(INVARIANTS.ussdFallback), "the USSD fallback must be on screen 5");
});

test("the countdown is on the waiting screen and shows the real time left", () => {
  // Invariant 3. It is the only reason it is safe to ask a client to leave the
  // page for their M-Pesa PIN prompt.
  const html = renderToStaticMarkup(
    <Pushed state={stateWith(holdWith(paymentView()), "pushed")} flow={noopFlow} seconds={140} />
  );

  assert.ok(html.includes("2:20"), "the countdown must be rendered, not implied");
});

test("a countdown at zero with a push still live says so instead of claiming to have expired", () => {
  // The server holds the slot through its grace window. A timer that said
  // "expired" here would be lying about the thing it exists to report, which is
  // the unexplained failure invariant 3 names.
  const html = renderToStaticMarkup(
    <Pushed state={stateWith(holdWith(paymentView()), "pushed")} flow={noopFlow} seconds={0} />
  );

  assert.ok(html.includes("Still checking with M-Pesa"));
  assert.ok(!html.includes("has run out"));
});

test("every control on the waiting screen meets the 52px floor", () => {
  const html = renderToStaticMarkup(
    <Pushed state={stateWith(holdWith(paymentView()), "pushed")} flow={noopFlow} seconds={140} />
  );

  for (const match of html.matchAll(/min-height:\s*(\d+)px/g)) {
    const value = Number(match[1]);
    assert.ok(
      value >= INVARIANTS.minTargetHeightPx,
      `a control is ${value}px, below the ${INVARIANTS.minTargetHeightPx}px floor`
    );
  }
});

test('"Pay at the shop instead" is gone, and the truth is in its place', () => {
  // That control implied the slot was held while the client made their way
  // over, and it is not. A WhatsApp link would have made the same implication
  // more politely, which is why it was not the replacement either.
  const html = readable(
    renderToStaticMarkup(
      <Pushed state={stateWith(holdWith(paymentView()), "pushed")} flow={noopFlow} seconds={140} />
    )
  );

  assert.ok(!/pay at the shop/i.test(html));
  assert.ok(!/whatsapp/i.test(html));
  assert.ok(html.includes("+254712000111"), "the shop's number replaces it");
  assert.ok(html.includes("not being held for you"), "and says plainly that the slot is not held");
});

test("the paid screen leads with the M-Pesa receipt", () => {
  // The design puts it above everything else and is right: it is the one thing
  // the client shows at the door.
  const paid = paymentView({
    state: "succeeded",
    push_outstanding: false,
    mpesa_receipt: "SJ42K19XQ7",
  });
  const html = renderToStaticMarkup(
    <Paid state={stateWith(holdWith(paid, { status: "confirmed" }), "paid")} />
  );

  assert.ok(html.indexOf("SJ42K19XQ7") < html.indexOf("Knotless braids"));
});

test("the paid screen promises exactly what slice 8 sends, and no schedule", () => {
  // Slice 6 refused to mention reminders at all, because none existed. Slice 8
  // built them, so the promise is now keepable — but it must stay vague about
  // the count: a booking made two hours out gets one reminder and one made next
  // week gets two, and naming a schedule would make the shorter case a broken
  // promise. See `notifications/reminders.py`.
  const paid = paymentView({ state: "succeeded", push_outstanding: false, mpesa_receipt: "SJ1" });
  const html = readable(
    renderToStaticMarkup(<Paid state={stateWith(holdWith(paid, { status: "confirmed" }), "paid")} />)
  );

  assert.ok(html.includes("confirmation by SMS"));
  assert.ok(/remind you before/i.test(html), "the reminder promise is now one we keep");
  assert.ok(!/24 hours before|2 hours before/i.test(html), "never a specific schedule");
  assert.ok(!/two reminders|2 reminders/i.test(html));
});

test("the failure screen names the reason and offers no deposit-free detour", () => {
  // Sending a client hunting through a service list at the worst possible
  // moment is not a remedy. The thing they wanted is still theirs for another
  // minute or two, which is what the retry is for.
  const failed = paymentView({
    state: "failed",
    push_outstanding: false,
    message: "There wasn't enough in that M-Pesa balance.",
  });
  const html = readable(
    renderToStaticMarkup(
      <Failed state={stateWith(holdWith(failed), "failed")} flow={noopFlow} seconds={90} />
    )
  );

  assert.ok(html.includes("There wasn't enough in that M-Pesa balance."));
  assert.ok(!/no deposit|without a deposit|deposit-free/i.test(html));
  assert.ok(html.includes("1:30"), "the countdown stays — the retry happens inside it");
});

test("screen 8 offers the re-point, and never promises an automatic refund", () => {
  // The design said "automatic refund within 24 hr". Nothing automatic exists,
  // the money is with the shop rather than with us, and a promise the product
  // cannot keep is the worst thing to put on the one screen where the client is
  // already unhappy.
  const lost = paymentView({
    state: "orphaned",
    push_outstanding: false,
    mpesa_receipt: "SJ42K19XQ7",
    slot_lost: true,
  });
  const html = readable(
    renderToStaticMarkup(
      <SlotLost state={stateWith(holdWith(lost, { status: "cancelled" }), "slotLost")} flow={noopFlow} />
    )
  );

  assert.ok(!/refund/i.test(html), "still no refund promise — nothing automatic exists");
  assert.ok(!/24 ?h|24 hour/i.test(html));
  // Slice 7 replaced the phone call with the client's own remedy: the deposit
  // is re-pointed at whatever time they pick. The phone number stays *below*
  // it as the fallback, because a re-point can lose its own race.
  assert.ok(html.includes("Pick another time"), "the remedy is the lead action");
  assert.ok(html.includes("comes with it"), "and it says the deposit travels");
  assert.ok(html.includes("+254712000111"), "the fallback number is still there");
});

test("screen 8 shows the support code the client reads down the phone", () => {
  // The owner dashboard is slice 9. A code nobody can look up would be
  // decoration; `payments/tests/test_support_code.py` proves the lookup works
  // now, and this proves the client is actually given the code to quote.
  const lost = paymentView({
    state: "orphaned",
    push_outstanding: false,
    mpesa_receipt: "SJ42K19XQ7",
    slot_lost: true,
  });
  const html = renderToStaticMarkup(
    <SlotLost state={stateWith(holdWith(lost, { status: "cancelled" }), "slotLost")} flow={noopFlow} />
  );

  assert.ok(html.includes("BK-4F7K2Q"));
  assert.ok(html.includes("Quote this code"));
  assert.ok(html.includes("tel:+254712000111"), "and the number to quote it to");
});
