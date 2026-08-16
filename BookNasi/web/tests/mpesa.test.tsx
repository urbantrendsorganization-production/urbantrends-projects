/**
 * The connect-M-Pesa screen's rendering rules.
 *
 * Everything about *where the money goes* is asserted on the server, in
 * `payments/tests/test_per_shop_till.py`, because that is where the decision is
 * made. What can only be checked here is what this screen shows a person, and
 * three of those things are load-bearing:
 *
 * 1. **A secret is never rendered.** The API returns masks, and a component
 *    that put a raw value into a `value` or a `placeholder` would undo the
 *    whole reason the column is encrypted — the credential would be in the DOM,
 *    in a screenshot, in a session recording.
 * 2. **"Not connected" says nothing was collected wrongly.** An owner reading a
 *    warning about money assumes the worst, and the true answer is reassuring:
 *    a shop is never quietly switched to somebody else's till.
 * 3. **A person who cannot fix a check is not given a Fix button.** M-Pesa is
 *    the first check behind a role the reader may not have, and a button that
 *    blanks the screen is worse than a sentence.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { INVARIANTS } from "@booknasi/tokens";
import { renderToStaticMarkup } from "react-dom/server";

import { Checklist, type Readiness } from "../components/setup/Checklist";
import { MpesaEditor, type Mpesa } from "../components/setup/MpesaEditor";

const TARGET = INVARIANTS.minTargetHeightPx;

const PASSKEY = "a-real-looking-passkey-9f3b";

function mpesa(overrides: Partial<Mpesa> = {}): Mpesa {
  return {
    collects_via: "own",
    mpesa_shortcode: "5550001",
    mpesa_till_number: "",
    mpesa_transaction_type: "",
    consumer_key_masked: "••••••••ey12",
    consumer_secret_masked: "••••••••cr34",
    passkey_masked: "••••••••9f3b",
    is_connected: true,
    platform_available: true,
    can_store_credentials: true,
    ...overrides,
  };
}

function render(overrides: Partial<Mpesa> = {}) {
  return renderToStaticMarkup(
    <MpesaEditor orgId="org-1" shopId="shop-1" mpesa={mpesa(overrides)} onChanged={() => {}} />
  );
}

test("no secret reaches the DOM, only its mask", () => {
  const html = render();

  assert.ok(!html.includes(PASSKEY));
  assert.ok(html.includes("••••••••9f3b"));
});

test("the secret inputs are empty, so saving without touching them keeps them", () => {
  /**
   * The mask is a placeholder, never a value. A component that pre-filled the
   * boxes with the mask would send eight bullets to the API as the new passkey
   * the first time an owner corrected their paybill number.
   */
  const html = render();

  assert.ok(html.includes('placeholder="••••••••9f3b"'));
  assert.ok(!html.includes('value="••••••••9f3b"'));
});

test("the secret inputs are password fields", () => {
  /** A salon laptop faces a counter. */
  const html = render();
  const passwordFields = html.match(/type="password"/g) ?? [];

  assert.equal(passwordFields.length, 3);
});

test("a connected paybill shop says where deposits go", () => {
  const html = render();

  assert.ok(html.includes("paybill 5550001"));
});

test("a connected till shop names the till, not the store number", () => {
  /**
   * These are different numbers, and the till is the one money lands in.
   * Reporting the store number would tell an owner their deposits arrive
   * somewhere they do not.
   */
  const html = render({
    mpesa_transaction_type: "CustomerBuyGoodsOnline",
    mpesa_till_number: "5550002",
  });

  assert.ok(html.includes("till 5550002"));
  // Narrower than `!html.includes("paybill")`, which the choice labels and the
  // Daraja instructions both fail for the right reasons. The claim is about the
  // status line: it must not report the store number as the destination.
  assert.ok(!html.includes("paybill 5550001"));
  assert.ok(!html.includes("Deposits go to paybill"));
});

test("not connected states that nothing was collected into the wrong account", () => {
  const html = render({ is_connected: false, mpesa_shortcode: "", passkey_masked: "" });

  assert.ok(html.includes("cannot be booked online"));
  assert.ok(html.includes("wrong account"));
});

test("an unset secret and a stored one read differently", () => {
  /** Otherwise the screen cannot tell an owner what is left to do. */
  const stored = render();
  const unset = render({ passkey_masked: "", consumer_key_masked: "", consumer_secret_masked: "" });

  assert.ok(stored.includes("Leave blank to keep it"));
  assert.ok(unset.includes("Not set yet"));
});

test("a credential that can no longer be decrypted says so", () => {
  /**
   * Not blank. Blank reads as "never set", and an owner who concludes the save
   * did not work will type it again — which is the one thing that would fix it,
   * arrived at by luck rather than by being told.
   */
  const html = render({ passkey_masked: "unreadable" });

  assert.ok(html.includes("can no longer read it"));
});

test("the platform option is hidden when the deployment has no platform till", () => {
  /** An option that would be refused on submit is worse than no option. */
  const html = render({ platform_available: false });

  assert.ok(!html.includes("BookNasi&#x27;s account"));
});

test("the till number field only appears for a Buy Goods connection", () => {
  const paybill = render();
  const till = render({
    mpesa_transaction_type: "CustomerBuyGoodsOnline",
    mpesa_till_number: "5550002",
  });

  assert.ok(!paybill.includes("Till number"));
  assert.ok(till.includes("Till number"));
  assert.ok(till.includes("head office number"));
});

test("saving is refused outright when the deployment cannot store credentials", () => {
  const html = render({ can_store_credentials: false });

  assert.ok(html.includes("cannot store credentials"));
});

test("every control clears the 52px floor", () => {
  const html = render({
    mpesa_transaction_type: "CustomerBuyGoodsOnline",
    mpesa_till_number: "5550002",
  });

  for (const match of html.matchAll(/min-height:\s*([0-9.]+)px/g)) {
    assert.ok(
      Number(match[1]) >= TARGET,
      `a control is ${match[1]}px, below the ${TARGET}px floor in CLAUDE.md §10`
    );
  }
});

test("the choices are buttons with aria-pressed, not radios", () => {
  /**
   * Same rule as `Toggle`. A 16px radio inside a 52px label passes an audit and
   * is still aimed at like a 16px radio.
   */
  const html = render();

  assert.ok(!html.includes('type="radio"'));
  assert.ok(html.includes('aria-pressed="true"'));
});

// --------------------------------------------------------------- the checklist

function readinessWith(done: boolean): Readiness {
  return {
    shop_id: "shop-1",
    is_bookable: false,
    booking_url: "https://mint-braids-kilimani.booknasi.co.ke",
    checks: [
      {
        key: "collects",
        done,
        title: "Connect your M-Pesa",
        detail: "Deposits need somewhere to land.",
        action: "mpesa",
      },
    ],
    deposit_free_services: [],
  };
}

test("an owner gets a Fix button for the M-Pesa check", () => {
  const html = renderToStaticMarkup(
    <Checklist
      readiness={readinessWith(false)}
      onGo={() => {}}
      reachable={["shop", "hours", "services", "staff", "mpesa"]}
    />
  );

  assert.ok(html.includes("Fix"));
});

test("a manager gets a sentence instead, because the tab is not theirs", () => {
  const html = renderToStaticMarkup(
    <Checklist
      readiness={readinessWith(false)}
      onGo={() => {}}
      reachable={["shop", "hours", "services", "staff"]}
    />
  );

  assert.ok(!html.includes(">Fix<"));
  assert.ok(html.includes("Ask the owner"));
});

test("and the check is still shown as outstanding to them", () => {
  /**
   * A checklist that reported the shop as fine because of who was looking would
   * be a checklist that lies. The shop genuinely is not bookable.
   */
  const html = renderToStaticMarkup(
    <Checklist
      readiness={readinessWith(false)}
      onGo={() => {}}
      reachable={["shop", "hours", "services", "staff"]}
    />
  );

  assert.ok(html.includes("Connect your M-Pesa"));
  assert.ok(!html.includes(">Done<"));
});
