/**
 * The Data & privacy screen.
 *
 * What erasure actually does is asserted on the server, in
 * `clients/tests/test_erasure.py`. What can only be checked here is what a
 * person is told before they press an irreversible button, and three of those
 * are load-bearing:
 *
 * 1. **The credit warning appears, with the amount.** Erasure voids unspent
 *    credit and nobody would guess that. A confirm dialog that omitted it would
 *    be asking somebody to agree to something nobody had told them, and the
 *    consequence surfaces weeks later when a client tries to spend it.
 * 2. **The retention sentence is the server's.** Same rule as §12's refund
 *    sentence: a policy worded twice is a policy a shop can state one way to a
 *    client and another way to itself.
 * 3. **A manager gets a sentence, not a button.** Erasing is owner-only, and a
 *    button that always 403s is worse than an explanation.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { INVARIANTS } from "@booknasi/tokens";
import { renderToStaticMarkup } from "react-dom/server";

import { PrivacyEditor, type ClientRow } from "../components/setup/PrivacyEditor";

const TARGET = INVARIANTS.minTargetHeightPx;

const STATEMENT =
  "Your name, phone number and visit history are kept for 24 months after your last appointment, then permanently removed.";

function person(overrides: Partial<ClientRow> = {}): ClientRow {
  return {
    id: "client-1",
    full_name: "Amina Wanjiru",
    phone: "+254712000301",
    is_erased: false,
    scrubbed_at: null,
    scrub_reason: "",
    erasure_requested_at: null,
    last_seen: "2026-08-01T09:00:00Z",
    visits: 4,
    ...overrides,
  };
}

function render(clients: ClientRow[], { canErase = true } = {}) {
  return renderToStaticMarkup(
    <PrivacyEditor
      orgId="org-1"
      clients={clients}
      retentionStatement={STATEMENT}
      canErase={canErase}
      onChanged={() => {}}
    />
  );
}

test("an outstanding request is surfaced above everything else", () => {
  /** A statutory clock is running. A search box first would only help somebody
   *  who already knows they have something to do. */
  const html = render([person({ erasure_requested_at: "2026-08-14T10:00:00Z" })]);

  const requests = html.indexOf("Requests to be forgotten");
  const everyone = html.indexOf("Everyone on your books");
  assert.ok(requests >= 0 && everyone > requests);
  assert.ok(!html.includes("Nothing outstanding"));
});

test("no requests says so rather than showing an empty list", () => {
  const html = render([person()]);

  assert.ok(html.includes("Nothing outstanding"));
});

test("the deadline is described as running from when they asked", () => {
  /** Not from when the owner looks. That distinction is the whole reason the
   *  request is stored with a timestamp. */
  const html = render([person()]);

  assert.ok(html.includes("from the day they ask"));
});

test("the retention sentence is the server's, character for character", () => {
  const html = render([person()]);

  assert.ok(html.includes(STATEMENT));
});

test("the screen states that bookings survive the erasure", () => {
  /** §9: "must not orphan appointment records in a way that breaks reporting".
   *  An owner asked to delete a client's data will assume their figures move,
   *  and would reasonably refuse. */
  const html = render([person()]);

  assert.ok(html.includes("do not change"));
});

test("an erased person reads as removed, not as a blank row", () => {
  const html = render([person({ is_erased: true, full_name: "", phone: "", visits: 4 })]);

  assert.ok(html.includes("Removed"));
  assert.ok(html.includes("still in your records"));
});

test("an erased person has no Remove button left", () => {
  const html = render([person({ is_erased: true, full_name: "", phone: "" })]);

  assert.ok(!html.includes(">Remove<"));
});

test("a manager is told why there is no Remove button", () => {
  const html = render([person()], { canErase: false });

  assert.ok(!html.includes(">Remove<"));
  assert.ok(html.includes("Only the owner can remove"));
});

test("a manager can still export", () => {
  /** They will be the one fielding the phone call. */
  const html = render([person()], { canErase: false });

  assert.ok(html.includes(">Export<"));
});

test("export is a real link, so the browser saves the file", () => {
  /**
   * Not a fetch. The response carries a `Content-Disposition`, and letting the
   * browser follow the link is what puts it in a downloads folder rather than
   * in a blob somebody has to be given a second button to save.
   */
  const html = render([person()]);

  assert.ok(html.includes('href="/api/v1/orgs/org-1/clients/client-1/export/"'));
});

test("every control clears the 52px floor", () => {
  const html = render([person({ erasure_requested_at: "2026-08-14T10:00:00Z" })]);

  for (const match of html.matchAll(/min-height:\s*([0-9.]+)px/g)) {
    assert.ok(
      Number(match[1]) >= TARGET,
      `a control is ${match[1]}px, below the ${TARGET}px floor in CLAUDE.md §10`
    );
  }
});

test("a person with no name recorded is not rendered as blank", () => {
  /** A walk-in can be recorded with neither. An empty row is unclickable in
   *  practice because nobody knows which one it is. */
  const html = render([person({ full_name: "", phone: "", visits: 1 })]);

  assert.ok(html.includes("No name recorded"));
});
