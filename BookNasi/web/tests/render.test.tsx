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
