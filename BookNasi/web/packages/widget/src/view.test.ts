/**
 * The eight screens, asserted as data. No DOM, no server, no timers.
 *
 * That is the whole reason `view.ts` returns a tree instead of touching one:
 * "the countdown is on this screen", "this button dispatches confirm", "the
 * word deposit came from the host's relabel" are all questions about a value,
 * and a value can be asked in a millisecond with nothing running.
 *
 * What is *not* tested here is anything `booking-core` already decides. Which
 * screen a payment state produces, whether Continue is allowed, what a blocked
 * button says — those have tests, in the module that makes the decision. A copy
 * of them here would pass while the widget was broken, because it would be
 * testing the same function twice.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  type AnyStaffSlot,
  type BookingState,
  type Hold,
  type PaymentView,
  type Service,
  type Shop,
  initialState,
} from "@booknasi/booking-core";

import { parseConfig } from "./config";
import { type ViewContext, render } from "./view";
import { type VNode, actionsIn, everyNode, textIn } from "./vdom";

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

const SHOP: Shop = {
  slug: "mint-braids-kilimani",
  name: "Mint Braids",
  address: "Wood Ave",
  area: "Kilimani",
  directions_url: "",
  phone: "+254712000111",
  logo_url: "",
  accent_color: "#C2521F",
  hold_ttl_minutes: 3,
  refund_window_hours: 24,
  deposit_credit_days: 60,
  opening_hours: [],
};

function slot(time: string, staff = "wanjiku"): AnyStaffSlot {
  return {
    starts_at: `2026-09-09T${time}:00:00Z`,
    ends_at: `2026-09-09T${time}:30:00Z`,
    local_time: `${time}:00`,
    duration_minutes: 240,
    staff_id: staff,
    staff_name: "Wanjiku",
  };
}

function payment(over: Partial<PaymentView> = {}): PaymentView {
  return {
    state: "pushed",
    amount_kes: 875,
    support_code: "BK-40219",
    mpesa_receipt: "",
    push_outstanding: true,
    message: "",
    slot_lost: false,
    ...over,
  };
}

function hold(over: Partial<Hold> = {}): Hold {
  return {
    id: "hold-1",
    status: "held",
    shop_name: "Mint Braids",
    starts_at: "2026-09-09T07:00:00Z",
    ends_at: "2026-09-09T11:00:00Z",
    local_time: "10:00",
    hold_expires_at: "2026-09-09T06:03:00Z",
    seconds_remaining: 120,
    staff_name: "Wanjiku",
    service_name: BRAIDS.name,
    price_kes: 3500,
    deposit_kes: 875,
    balance_kes: 2625,
    payment: null,
    shop_phone: "+254712000111",
    refund_window_hours: 24,
    deposit_credit_days: 60,
    ...over,
  };
}

function ctx(over: Partial<ViewContext> = {}): ViewContext {
  return {
    config: parseConfig({ shop: SHOP.slug }).config!,
    seconds: 120,
    today: "2026-09-09",
    ...over,
  };
}

function state(over: Partial<BookingState> = {}): BookingState {
  return { ...initialState, shop: SHOP, services: [BRAIDS], ...over };
}

const text = (node: VNode) => textIn(node);
const classes = (node: VNode) =>
  everyNode(node).map((child) => String(child.attrs.class ?? "")).join(" ");

// ------------------------------------------------------ CLAUDE.md §10, drawn

test("every control is on the 52px floor's class list", () => {
  // The floor itself lives in css.ts, in px, and check-widget.mjs proves that.
  // What a stylesheet cannot see is whether the screens use it — a button that
  // carries none of these classes has no height rule at all.
  const sized = ["bn-target", "bn-cta", "bn-slot", "bn-day", "bn-phone-input"];
  const screens: BookingState[] = [
    state(),
    state({ step: "staff", service: BRAIDS, staffChoice: "anyone" }),
    state({ step: "confirm", service: BRAIDS, slot: slot("07"), phone: "0712345678" }),
    state({ step: "held", hold: hold() }),
    state({ step: "pushed", hold: hold({ payment: payment() }) }),
    state({ step: "slotLost", hold: hold({ payment: payment({ slot_lost: true }) }) }),
  ];

  for (const screen of screens) {
    for (const node of everyNode(render(screen, ctx()))) {
      if (node.tag !== "button" && node.tag !== "input") continue;
      const carried = String(node.attrs.class ?? "");
      assert.ok(
        sized.some((name) => carried.includes(name)),
        `${screen.step}: a ${node.tag} with class "${carried}" has no target-height class`,
      );
    }
  }
});

test("the slot grid is the three-per-row container and nothing else", () => {
  const screen = state({
    step: "slot",
    service: BRAIDS,
    staffChoice: "anyone",
    date: "2026-09-09",
    availability: {
      date: "2026-09-09",
      service_id: BRAIDS.id,
      any_staff: [slot("07"), slot("08"), slot("09"), slot("14")],
      by_staff: [],
    },
  });

  const grids = everyNode(render(screen, ctx())).filter((node) =>
    String(node.attrs.class ?? "").includes("bn-slots"),
  );

  // Morning and afternoon, and the slots sit directly inside them so the CSS
  // grid actually applies to the chips rather than to a wrapper.
  assert.equal(grids.length, 2);
  assert.equal(grids[0].children.length, 3);
  assert.equal(grids[1].children.length, 1);
});

test("the countdown is on every screen with a live hold, and is never a bare number", () => {
  for (const step of ["held", "pushed", "failed"] as const) {
    const screen = state({ step, hold: hold({ payment: payment() }) });
    const rendered = render(screen, ctx({ seconds: 119 }));

    assert.ok(classes(rendered).includes("bn-panel-hold"), `${step}: no countdown panel`);
    assert.ok(text(rendered).includes("1:59"), `${step}: no countdown`);
  }
});

test("a timer at zero with a push outstanding says so, instead of claiming an expiry", () => {
  // The server holds the slot through a grace window. A screen that said
  // "expired" here would be the unexplained failure invariant 3 exists to stop.
  const screen = state({ step: "pushed", hold: hold({ payment: payment({ push_outstanding: true }) }) });

  const rendered = render(screen, ctx({ seconds: 0 }));

  assert.ok(text(rendered).includes("Still checking with M-Pesa"));
  assert.ok(!text(rendered).includes("expired"));
});

test("the *334# fallback is on the waiting screen and is not behind a tap", () => {
  const screen = state({ step: "pushed", hold: hold({ payment: payment() }) });
  const rendered = render(screen, ctx());

  assert.ok(text(rendered).includes("*334#"));
  // Not inside anything clickable: a fallback the client has to find is not a
  // fallback on the screen where the push did not arrive.
  for (const node of everyNode(rendered)) {
    if (node.tag === "button" && textIn(node).includes("*334#")) {
      assert.fail("the USSD fallback is inside a button");
    }
  }
});

test("the refund and forfeit terms are on the confirm screen, before the money moves", () => {
  const screen = state({ step: "confirm", service: BRAIDS, slot: slot("07"), phone: "0712345678" });

  const rendered = text(render(screen, ctx()));

  // All four outcomes of the policy settled on 14 August 2026 — CLAUDE.md §12.
  assert.ok(rendered.includes("24 hours before"));
  assert.ok(rendered.includes("refunded"));
  assert.ok(rendered.includes("credit at this shop"));
  assert.ok(rendered.includes("60 days"));
  assert.ok(rendered.includes("if the shop cancels"));
});

test("the terms are on screen 1 too, priced, before anything is asked", () => {
  const rendered = text(render(state(), ctx()));

  assert.ok(rendered.includes("KES 875"));
  assert.ok(rendered.includes("refunded"));
});

// ------------------------------------------------------------- the copy token

test("a host relabelling the deposit relabels every screen that names it", () => {
  const branded = ctx({ config: parseConfig({ shop: SHOP.slug, "deposit-word": "reservation fee" }).config! });
  const confirm = state({ step: "confirm", service: BRAIDS, slot: slot("07"), phone: "0712345678" });

  const first = text(render(state(), branded));
  const paying = text(render(confirm, branded));

  for (const screen of [first, paying]) {
    assert.ok(screen.includes("reservation fee"), screen.slice(0, 200));
    assert.ok(!/deposit/i.test(screen), "the default word survived a relabel");
  }
  assert.ok(paying.includes("Reservation fee now"));
});

test("relabelling cannot remove the terms", () => {
  // CLAUDE.md §10: the sentence may be translated or relabelled, never removed.
  const branded = ctx({ config: parseConfig({ shop: SHOP.slug, "deposit-word": "fee" }).config! });
  const confirm = state({ step: "confirm", service: BRAIDS, slot: slot("07"), phone: "0712345678" });

  assert.ok(text(render(confirm, branded)).includes("miss the appointment and it is kept"));
});

// ------------------------------------------------------------------ wiring

test("each control dispatches the action it is labelled with", () => {
  const services = render(state(), ctx());
  assert.deepEqual(actionsIn(services), [{ type: "chooseService", id: BRAIDS.id }]);

  const staff = state({ step: "staff", service: BRAIDS, staffChoice: "anyone" });
  assert.deepEqual(actionsIn(render(staff, ctx()))[0], { type: "back" });
  assert.deepEqual(actionsIn(render(staff, ctx()))[1], { type: "chooseStaff", id: "anyone" });
});

test("the confirm button dispatches confirm, and the phone input dispatches setPhone", () => {
  const screen = state({ step: "confirm", service: BRAIDS, slot: slot("07"), phone: "0712345678" });

  const actions = actionsIn(render(screen, ctx()));

  assert.ok(actions.some((action) => action.type === "confirm"));
  assert.ok(actions.some((action) => action.type === "setPhone"));
});

test("a disabled confirm still carries its action, and says why it is disabled", () => {
  // The button is disabled by the attribute, so the click never fires. Stripping
  // the action as well would mean the enabled and disabled trees differ in two
  // places, and the patcher would have to rebind on every keystroke.
  const screen = state({ step: "confirm", service: BRAIDS, slot: slot("07"), phone: "" });
  const rendered = render(screen, ctx());

  const cta = everyNode(rendered).find((node) => String(node.attrs.class ?? "").includes("bn-cta"))!;
  assert.equal(cta.attrs.disabled, true);
  assert.equal(textIn(cta), "Enter your M-Pesa number");
  assert.deepEqual(cta.on.click, { type: "confirm" });
});

test("a slot chip dispatches its own start time", () => {
  const screen = state({
    step: "slot",
    service: BRAIDS,
    staffChoice: "anyone",
    date: "2026-09-09",
    availability: { date: "2026-09-09", service_id: BRAIDS.id, any_staff: [slot("08")], by_staff: [] },
  });

  assert.ok(
    actionsIn(render(screen, ctx())).some(
      (action) => action.type === "chooseSlot" && action.startsAt === "2026-09-09T08:00:00Z",
    ),
  );
});

test("selection is aria-pressed, so it is a state and not only a colour", () => {
  const screen = state({ step: "staff", service: BRAIDS, staffChoice: "anyone" });

  const pressed = everyNode(render(screen, ctx())).filter(
    (node) => node.attrs["aria-pressed"] === true,
  );

  assert.equal(pressed.length, 1);
});

// ------------------------------------------------------------- screens 5 to 8

test("the paid screen leads with the M-Pesa code, because it is the proof at the door", () => {
  const screen = state({
    step: "paid",
    hold: hold({ payment: payment({ state: "succeeded", mpesa_receipt: "SJ42K19XQ", push_outstanding: false }) }),
  });

  const rendered = text(render(screen, ctx()));

  assert.ok(rendered.indexOf("SJ42K19XQ") < rendered.indexOf("Balance at the shop"));
});

test("screen 8 offers to carry the payment, and never promises an automatic refund", () => {
  const screen = state({
    step: "slotLost",
    hold: hold({ payment: payment({ state: "succeeded", slot_lost: true, push_outstanding: false }) }),
  });
  const rendered = render(screen, ctx());

  assert.ok(actionsIn(rendered).some((action) => action.type === "pickAnotherTime"));
  assert.ok(text(rendered).includes("BK-40219"));
  assert.ok(!/automatic/i.test(text(rendered)));
});

test("the payment screens have no Back arrow", () => {
  // The money either moved or it did not, and a back arrow that appears to undo
  // it is the most expensive lie on these screens.
  for (const step of ["pushed", "paid", "failed", "timedOut", "slotLost"] as const) {
    const screen = state({ step, hold: hold({ payment: payment() }) });

    assert.ok(
      !actionsIn(render(screen, ctx())).some((action) => action.type === "back"),
      `${step} offers a Back`,
    );
  }
});

test("the shop's number comes with the sentence that has to sit next to it", () => {
  const screen = state({ step: "pushed", hold: hold({ payment: payment() }) });

  const rendered = text(render(screen, ctx()));

  assert.ok(rendered.includes("+254712000111"));
  assert.ok(rendered.includes("not being held for you once the timer runs out"));
});

// ------------------------------------------------------------------ layout

test("a very long service name keeps the price in its own column", () => {
  // Not an edge case: shops write "Knotless braids, medium, waist length, with
  // beads and a wash". The name grows, the price does not move.
  const long = { ...BRAIDS, name: "Knotless braids ".repeat(20) };
  const rendered = render(state({ services: [long] }), ctx());

  const card = everyNode(rendered).find((node) =>
    String(node.attrs.class ?? "").includes("bn-card-target"),
  )!;
  const [name, price] = (card.children[0] as VNode).children as VNode[];

  assert.equal(name.attrs.class, "bn-grow");
  assert.ok(String(price.attrs.class).includes("bn-fixed"));
});

test("the day strip opens on the day it was given, not on a UTC guess", () => {
  const rendered = render(
    state({ step: "slot", service: BRAIDS, staffChoice: "anyone", date: "2026-09-09" }),
    ctx({ today: "2026-09-09" }),
  );

  const days = everyNode(rendered).filter((node) => String(node.attrs.class ?? "") === "bn-day");

  assert.equal(days.length, 7);
  assert.equal(days[0].attrs["aria-pressed"], true);
});
