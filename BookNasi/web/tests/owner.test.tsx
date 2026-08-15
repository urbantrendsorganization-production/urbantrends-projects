/**
 * The owner dashboard's rendering rules, which are all rules about honesty.
 *
 * Three of them cannot be checked anywhere else:
 *
 * 1. **A null rate prints an em dash, never `0 %`.** The API is careful to send
 *    null when a denominator is zero; a formatter that coerced it would undo
 *    that at the last possible moment, on the screen, where it would be read as
 *    a measurement.
 * 2. **No clay button.** The design's accent discipline: this screen has no
 *    primary action, so clay appears only as data bars. It is checked here
 *    rather than by eye because "add a button" is the most natural change
 *    anybody would make to a page like this.
 * 3. **The headline never contradicts the verdict.** The conclusion is chosen
 *    on the server and worded here, and the whole point of that split is that
 *    the wording cannot drift into a different claim.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { renderToStaticMarkup } from "react-dom/server";

import { Overview, type Report, type StaffRow } from "../components/owner/Overview";
import { percent, barWidth, movement } from "../components/owner/format";
import { headlineFor } from "../components/owner/headline";

const EMPTY_STAFF: StaffRow = {
  staff_id: "s1",
  display_name: "Wanjiku",
  shop_id: "shop-1",
  shop_name: "Mint Braids Kilimani",
  services: 0,
  revenue_kes: 0,
  deposits_kes: 0,
  no_shows: 0,
  unresolved: 0,
  shortened: 0,
  booked_minutes: 0,
  capacity_minutes: 0,
  utilisation: null,
};

function report(overrides: Partial<Report> = {}): Report {
  return {
    period: {
      starts_on: "2026-07-16",
      ends_on: "2026-08-14",
      days: 30,
      previous: { starts_on: "2026-06-16", ends_on: "2026-07-15", days: 30 },
    },
    scope: {
      organization_id: "org-1",
      organization_name: "Mint Braids",
      shop_id: null,
      shops: [{ id: "shop-1", name: "Mint Braids Kilimani" }],
    },
    verdict: "deposits_working",
    outcomes: { completed: 40, no_show: 3, cancelled: 5, unresolved: 0, upcoming: 2, total: 50 },
    no_show: {
      rate: 3 / 43,
      counted_out_of: 43,
      previous_rate: 0.18,
      previous_counted_out_of: 40,
    },
    revenue_kes: 140_000,
    money: {
      collected_kes: 35_000,
      forfeited_kes: 2_625,
      credit_issued_kes: 875,
      refund_due_kes: 0,
      pushes: 48,
      pushes_succeeded: 42,
      stk_completion: 42 / 48,
    },
    clients: {
      seen: 30,
      repeat: 11,
      repeat_rate: 11 / 30,
      attributed: 30,
      completed: 40,
      attributed_share: 0.75,
    },
    staff: [EMPTY_STAFF],
    today: [
      {
        shop_id: "shop-1",
        shop_name: "Mint Braids Kilimani",
        appointments: 6,
        walk_ins: 2,
        booked_minutes: 300,
        capacity_minutes: 1080,
        load: 300 / 1080,
      },
    ],
    ...overrides,
  };
}

test("a rate with no denominator prints a dash, never zero per cent", () => {
  assert.equal(percent(null), "—");
  assert.equal(percent(0), "0.0 %");
  assert.equal(barWidth(null), "0%");
});

test("a bar can never be drawn past full or below empty", () => {
  assert.equal(barWidth(1.4), "100.0%");
  assert.equal(barWidth(-0.2), "0.0%");
});

test("movement needs both sides before it reports a direction", () => {
  assert.equal(movement(0.05, null), null);
  assert.equal(movement(0.05, 0.18), "down");
  assert.equal(movement(0.18, 0.05), "up");
  assert.equal(movement(0.05, 0.052), "flat");
});

test("an unrostered stylist reads as absent rather than as idle", () => {
  const markup = renderToStaticMarkup(<Overview report={report()} />);

  assert.match(markup, /Not rostered/);
  assert.doesNotMatch(markup, /0 % · 0 hr of 0 hr/);
});

test("the screen has no clay-filled button — it has no primary action", () => {
  const markup = renderToStaticMarkup(<Overview report={report()} />);
  const buttons = markup.match(/<button[^>]*>/g) ?? [];

  for (const button of buttons) {
    assert.doesNotMatch(
      button,
      /background:\s*var\(--bn-accent\)|background:\s*var\(--bn-clay-600\)/,
      `a filled clay button reached the owner dashboard: ${button}`
    );
  }
});

test("clay is present, as a data bar", () => {
  const markup = renderToStaticMarkup(<Overview report={report()} />);

  assert.match(markup, /--bn-clay-600/);
  assert.match(markup, /--bn-track/);
});

test("the meters are decoration and the number is the content", () => {
  /* Which is also what keeps an 8px element inside the 52px target floor:
     `aria-hidden` is the exemption `check-invariants.mjs` reads, and it cannot
     be added without making the element genuinely unreachable. */
  const markup = renderToStaticMarkup(<Overview report={report()} />);
  const bars = markup.match(/height:8px/g) ?? [];

  assert.ok(bars.length > 0, "no meters rendered");
  assert.equal((markup.match(/aria-hidden="true"[^>]*style="background:var\(--bn-track\)/g) ?? []).length, bars.length);
});

test("every rate is printed with the denominator it was computed over", () => {
  const markup = renderToStaticMarkup(<Overview report={report()} />);

  assert.match(markup, /of 43 finished bookings/);
  assert.match(markup, /11 of 30 came back/);
});

test("the repeat rate says how much of the trade it describes", () => {
  /* A walk-in carries no client record, so on a walk-in-heavy shop this rate is
     a statement about the booked half of the business. */
  const markup = renderToStaticMarkup(<Overview report={report()} />);

  assert.match(markup, /30 of 40 finished bookings that carry a client name/);
});

test("unfinished bookings are declared, not quietly dropped", () => {
  const withUnresolved = report({
    outcomes: { completed: 40, no_show: 3, cancelled: 5, unresolved: 7, upcoming: 2, total: 57 },
  });
  const markup = renderToStaticMarkup(<Overview report={withUnresolved} />);

  assert.match(markup, /7 bookings in this period were never finished or marked missed/);
  assert.match(markup, /not in the figures above/);
});

test("a period with nothing unfinished says nothing about it", () => {
  const markup = renderToStaticMarkup(<Overview report={report()} />);

  assert.doesNotMatch(markup, /never finished or marked missed/);
});

test("a shop taking no deposits is told so, not congratulated", () => {
  const copy = headlineFor("no_deposits");

  assert.match(copy.headline, /not taking deposits/i);
  assert.equal(copy.tone, "fail");
  assert.notEqual(copy.headline, headlineFor("deposits_working").headline);
});

test("an unknown verdict falls back to the claim that asserts least", () => {
  assert.equal(headlineFor("something_new").headline, headlineFor("steady").headline);
});

test("the headline is rendered from the server's verdict", () => {
  const markup = renderToStaticMarkup(<Overview report={report({ verdict: "no_shows_rising" })} />);

  assert.match(markup, /No-shows are up/);
  assert.doesNotMatch(markup, /Deposits are working/);
});

test("billed and collected are two columns and are never summed", () => {
  const rows: StaffRow[] = [
    { ...EMPTY_STAFF, services: 12, revenue_kes: 42_000, deposits_kes: 10_500, no_shows: 1 },
  ];
  const markup = renderToStaticMarkup(<Overview report={report({ staff: rows })} />);

  assert.match(markup, /KES 42,000/);
  assert.match(markup, /KES 10,500/);
  assert.doesNotMatch(markup, /KES 52,500/);
});

test("deposits and no-shows stay adjacent in the table", () => {
  /* The design says to keep them together because the adjacency is the
     argument: the stylist with no deposits is the one with the no-shows. */
  const markup = renderToStaticMarkup(<Overview report={report()} />);
  const headers = [...markup.matchAll(/<th[^>]*>([^<]+)<\/th>/g)].map((m) => m[1]);

  assert.equal(headers.indexOf("No-shows") - headers.indexOf("Deposits"), 1);
});

test("shortened walk-ins are explained where they distort the number", () => {
  const rows: StaffRow[] = [{ ...EMPTY_STAFF, shortened: 3, capacity_minutes: 540, utilisation: 0.2 }];
  const markup = renderToStaticMarkup(<Overview report={report({ staff: rows })} />);

  assert.match(markup, /3 shortened/);
  assert.match(markup, /pull utilisation down/);
});

test("the comparison names the dates it is against", () => {
  /* There is no pre-BookNasi baseline and the screen must never imply one. */
  const markup = renderToStaticMarkup(<Overview report={report()} />);

  assert.match(markup, /compared with/);
  assert.match(markup, /16 Jun – 15 Jul 2026/);
});

test("a shop with nothing to compare against says so", () => {
  const markup = renderToStaticMarkup(
    <Overview
      report={report({
        no_show: { rate: 0.07, counted_out_of: 43, previous_rate: null, previous_counted_out_of: 0 },
      })}
    />
  );

  assert.match(markup, /nothing in the period before this one to compare against/);
});

test("a shop closed today reads as closed rather than as empty", () => {
  const markup = renderToStaticMarkup(
    <Overview
      report={report({
        today: [
          {
            shop_id: "shop-1",
            shop_name: "Mint Braids Kilimani",
            appointments: 0,
            walk_ins: 0,
            booked_minutes: 0,
            capacity_minutes: 0,
            load: null,
          },
        ],
      })}
    />
  );

  assert.match(markup, /Closed today/);
});
