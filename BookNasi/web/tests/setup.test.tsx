/**
 * The setup screen's rendering rules.
 *
 * Most of what this screen does is forms against endpoints that already have
 * their own tests. Four things cannot be checked anywhere else, and all four
 * are places where a plausible tidy-up would quietly break a rule that lives
 * in CLAUDE.md rather than in the code being edited:
 *
 * 1. **The refund sentence is the real one.** §12 says
 *    `money.refundSentence` is the one place the terms are worded. The
 *    settings screen previews it, and a preview that was a second copy would
 *    be worse than no preview — it would show an owner a policy their clients
 *    are not agreeing to.
 * 2. **The deposit-free consequence is stated, not implied.** §5's rule is
 *    counter-intuitive, and the screen where somebody sets a service to "no
 *    deposit" is the only place it can be explained in time.
 * 3. **Every control clears the 52 px floor**, including the toggles that
 *    started life as native checkboxes.
 * 4. **The checklist never invents a verdict.** It renders what the server
 *    computed, in the server's order, and offers a way to fix only what is
 *    outstanding.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { INVARIANTS } from "@booknasi/tokens";
import { refundSentence } from "@booknasi/booking-core";
import { renderToStaticMarkup } from "react-dom/server";

import { Checklist, type Readiness } from "../components/setup/Checklist";
import { ServicesEditor, type Service } from "../components/setup/ServicesEditor";
import { Toggle, Tick } from "../components/setup/primitives";

const TARGET = INVARIANTS.minTargetHeightPx;

function readiness(overrides: Partial<Readiness> = {}): Readiness {
  return {
    shop_id: "shop-1",
    is_bookable: false,
    booking_url: "https://mint-braids-kilimani.booknasi.co.ke",
    checks: [
      { key: "hours", done: true, title: "Set your opening hours", detail: "Open 6 days a week.", action: "hours" },
      { key: "services", done: true, title: "Add what you sell", detail: "2 services.", action: "services" },
      { key: "deposits", done: true, title: "Take a deposit", detail: "1 of 2 bookable online.", action: "services" },
      { key: "staff", done: true, title: "Add the people", detail: "2 bookable.", action: "staff" },
      { key: "rosters", done: false, title: "Say which days each person works", detail: "Nobody works a day the shop is open.", action: "staff" },
      { key: "skills", done: false, title: "Say who does which service", detail: "A stylist offers nothing until you tick it.", action: "staff" },
      { key: "fits", done: false, title: "Leave a shift long enough", detail: "No shift is long enough.", action: "staff" },
    ],
    deposit_free_services: [],
    ...overrides,
  };
}

function service(overrides: Partial<Service> = {}): Service {
  return {
    id: "svc-1",
    name: "Knotless braids, medium, waist length",
    description: "",
    duration_minutes: 240,
    price: 3500,
    deposit_mode: "percent",
    deposit_value: "25",
    deposit_amount: 875,
    is_active: true,
    is_publicly_listed: true,
    is_publicly_bookable: true,
    ...overrides,
  };
}

function servicesMarkup(overrides: { services?: Service[]; hours?: number; days?: number } = {}) {
  return renderToStaticMarkup(
    <ServicesEditor
      orgId="org-1"
      shopId="shop-1"
      services={overrides.services ?? [service()]}
      refundWindowHours={overrides.hours ?? 24}
      depositCreditDays={overrides.days ?? 60}
      onChanged={() => {}}
    />
  );
}

// ------------------------------------------------- the terms, worded once

test("the cancellation preview is the exact sentence the client will read", () => {
  const markup = servicesMarkup({ hours: 24, days: 60 });

  // Character for character, from `booking-core`. A paraphrase here is a shop
  // shown one policy while its clients agree to another.
  assert.ok(markup.includes(refundSentence(24, 60)));
});

test("the preview tracks the shop's own numbers, not the defaults", () => {
  const markup = servicesMarkup({ hours: 48, days: 90 });

  assert.ok(markup.includes(refundSentence(48, 90)));
  assert.ok(!markup.includes(refundSentence(24, 60)));
});

test("the two outcomes a shop cannot set are stated as fixed", () => {
  const markup = servicesMarkup();

  // §12: the no-show forfeit and the shop-cancels refund are not
  // shop-configurable, and a settings screen that offered fields for them
  // would be offering a term no client would accept.
  assert.ok(/not yours to set/i.test(markup));
  assert.ok(!/no.show/i.test(stripProse(markup)), "no field for the no-show outcome");
});

/** Field labels only — the prose deliberately mentions these outcomes. */
function stripProse(markup: string): string {
  return (markup.match(/<span[^>]*text-label-size[^>]*>[^<]*<\/span>/g) ?? []).join(" ");
}

// -------------------------------------------- §5's rule, where it is needed

test("a service with no deposit says it cannot be booked online", () => {
  const markup = servicesMarkup({
    services: [service({ deposit_mode: "none", deposit_value: null, deposit_amount: 0, is_publicly_bookable: false })],
  });

  assert.ok(/Staff and walk-ins only/.test(markup));
  assert.ok(/No deposit/.test(markup));
});

test("a service that takes a deposit reports the figure the server computed", () => {
  const markup = servicesMarkup({ services: [service({ deposit_amount: 875 })] });

  // 875, not 25% of 3500 recomputed here. `booking-core/money.ts` refuses to
  // compute a deposit for the same reason: a client-side percentage rounds
  // differently on some price sooner or later.
  assert.ok(markup.includes("KES 875"));
  assert.ok(/Bookable online/.test(markup));
});

test("the badge leads with the consequence, not the cause", () => {
  const bookable = servicesMarkup({ services: [service()] });
  const not = servicesMarkup({
    services: [service({ deposit_mode: "none", deposit_value: null, deposit_amount: 0, is_publicly_bookable: false })],
  });

  // "Bookable online" is what an owner is looking for when a service is
  // missing from their page; "no deposit" is only the reason.
  assert.ok(bookable.includes("Bookable online"));
  assert.ok(not.includes("Staff and walk-ins only"));
});

// ------------------------------------------------------ the checklist

test("the checklist renders the server's checks in the server's order", () => {
  const report = readiness();
  const markup = renderToStaticMarkup(<Checklist readiness={report} onGo={() => {}} />);

  const positions = report.checks.map((check) => markup.indexOf(check.title));
  assert.ok(positions.every((position) => position > -1), "every check is on the screen");
  assert.deepEqual([...positions].sort((a, b) => a - b), positions, "in order");
});

test("only outstanding items offer a way to fix them", () => {
  const report = readiness();
  const markup = renderToStaticMarkup(<Checklist readiness={report} onGo={() => {}} />);

  const fixes = markup.match(/>Fix</g) ?? [];
  const done = markup.match(/>Done</g) ?? [];
  assert.equal(fixes.length, report.checks.filter((c) => !c.done).length);
  assert.equal(done.length, report.checks.filter((c) => c.done).length);
});

test("a shop that is not ready says so and does not congratulate itself", () => {
  const markup = renderToStaticMarkup(<Checklist readiness={readiness()} onGo={() => {}} />);

  assert.ok(/3 things left/.test(markup));
  assert.ok(!/is live/.test(markup));
});

test("a shop that is ready leads with the link, because that is the next action", () => {
  const report = readiness({
    is_bookable: true,
    checks: readiness().checks.map((check) => ({ ...check, done: true })),
  });
  const markup = renderToStaticMarkup(<Checklist readiness={report} onGo={() => {}} />);

  assert.ok(/booking page is live/.test(markup));
  assert.ok(markup.includes("mint-braids-kilimani.booknasi.co.ke"));
});

test("one outstanding item is a thing, not things", () => {
  const checks = readiness().checks.map((check, index) => ({ ...check, done: index !== 6 }));
  const markup = renderToStaticMarkup(<Checklist readiness={readiness({ checks })} onGo={() => {}} />);

  assert.ok(/1 thing left/.test(markup));
});

test("services hidden from the booking page are named, even when the shop is ready", () => {
  const report = readiness({
    is_bookable: true,
    checks: readiness().checks.map((check) => ({ ...check, done: true })),
    deposit_free_services: [{ id: "s2", name: "Beard trim" }],
  });
  const markup = renderToStaticMarkup(<Checklist readiness={report} onGo={() => {}} />);

  // A shop can pass every check with four of its five services silently
  // invisible online. "Live" without this line would be true and misleading.
  assert.ok(markup.includes("Beard trim"));
  assert.ok(/not online/.test(markup));
});

test("a ready shop with nothing hidden says nothing about hidden services", () => {
  const report = readiness({
    is_bookable: true,
    checks: readiness().checks.map((check) => ({ ...check, done: true })),
  });
  const markup = renderToStaticMarkup(<Checklist readiness={report} onGo={() => {}} />);

  assert.ok(!/not online/.test(markup));
});

// -------------------------------------------------- CLAUDE.md §10, invariant 1

test("the toggle is a full target, not a checkbox inside one", () => {
  const markup = renderToStaticMarkup(
    <Toggle checked={false} onChange={() => {}} label="Tuesday" />
  );

  assert.ok(markup.includes(`min-height:${TARGET}px`));
  // The native checkbox this replaced was 18px of box inside 52px of label:
  // a correct hit area that still reads and is aimed at as an 18px box.
  assert.ok(!markup.includes('type="checkbox"'));
});

test("the toggle carries its state where a screen reader can read it", () => {
  const on = renderToStaticMarkup(<Toggle checked onChange={() => {}} label="Tuesday" />);
  const off = renderToStaticMarkup(<Toggle checked={false} onChange={() => {}} label="Tuesday" />);

  assert.ok(on.includes('aria-pressed="true"'));
  assert.ok(off.includes('aria-pressed="false"'));
});

test("the drawn tick is hidden from the accessibility tree", () => {
  // It duplicates `aria-pressed`, and being hidden is also what makes it
  // decoration rather than a 22px target.
  assert.ok(renderToStaticMarkup(<Tick checked />).includes('aria-hidden="true"'));
});

test("every control on the services screen clears the floor", () => {
  const markup = servicesMarkup();

  const heights = [...markup.matchAll(/min-height:(\d+)px/g)].map((match) => Number(match[1]));
  assert.ok(heights.length > 0, "there are sized controls to check");
  assert.ok(
    heights.every((height) => height >= TARGET),
    `every min-height is at least ${TARGET}px, got ${heights.join(", ")}`
  );
});

test("the checklist's own buttons clear the floor", () => {
  const markup = renderToStaticMarkup(<Checklist readiness={readiness()} onGo={() => {}} />);

  const heights = [...markup.matchAll(/min-height:(\d+)px/g)].map((match) => Number(match[1]));
  assert.ok(heights.every((height) => height >= TARGET));
});
