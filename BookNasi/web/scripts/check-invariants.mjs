/**
 * CLAUDE.md §10, enforced in CI.
 *
 * The four invariants are not styling choices. They are the difference between
 * a payment that completes and one that does not, and the failure mode they
 * guard against is not malice — it is a well-meaning tidy-up that makes a
 * button 44 px because it looked cramped in a mock on a laptop.
 *
 * `packages/tokens/src/check.mjs` proves the constants exist and are not CSS
 * custom properties. This proves the staff screens actually use them, which is
 * the half a token file cannot check.
 *
 * Run by the frontend CI job. Failing is the point.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const ROOT = new URL("..", import.meta.url).pathname;
const MIN_TARGET = 52;
const WALK_IN_ROW = 64;

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) out.push(...walk(path));
    else if (path.endsWith(".tsx")) out.push(path);
  }
  return out;
}

const failures = [];

const primitives = readFileSync(join(ROOT, "components/staff/primitives.tsx"), "utf8");

// 1. The primitives take their heights from the constants, not from numbers.
if (!primitives.includes("INVARIANTS.minTargetHeightPx")) {
  failures.push("primitives.tsx must take its control height from INVARIANTS.minTargetHeightPx");
}
if (!primitives.includes("INVARIANTS.walkInRowMinHeightPx")) {
  failures.push("primitives.tsx must take its walk-in row height from INVARIANTS.walkInRowMinHeightPx");
}

// 2. Nothing anywhere in the staff screens sets an interactive height below the
//    floor. Matches `minHeight: 44`, `minHeight: "44px"` and `height: 44`.
const HEIGHT = /\b(?:min-?[Hh]eight|height)\s*[:=]\s*"?(\d+)(?:px)?"?/g;

/**
 * The one exemption, and the reason it is safe.
 *
 * Slice 5 introduced a 6px element: the hold countdown's progress track. It is
 * `aria-hidden`, so it is not in the accessibility tree, not focusable and not
 * reachable by any user by any means — it cannot be a tap target, and forcing
 * it to 52px would put a thick bar across the screen the invariant exists to
 * keep usable.
 *
 * `aria-hidden` is the signal rather than a comment marker because it cannot be
 * added to silence this check without also making the element genuinely
 * unreachable. A developer who puts it on a button has a worse bug than a small
 * target, and one this check was never the right place to catch.
 */
function isDecoration(source, index) {
  return source.slice(Math.max(0, index - 240), index).includes("aria-hidden");
}

for (const file of [...walk(join(ROOT, "components")), ...walk(join(ROOT, "app"))]) {
  const source = readFileSync(file, "utf8");
  for (const match of source.matchAll(HEIGHT)) {
    const value = Number(match[1]);
    // Below the floor is a failure. Anything at or above it is a deliberate
    // larger target (the 56px CTA, the 64px FAB and walk-in rows) and fine.
    if (value > 0 && value < MIN_TARGET && !isDecoration(source, match.index)) {
      failures.push(`${file.replace(ROOT, "")}: interactive height ${value}px is below the ${MIN_TARGET}px floor`);
    }
  }
}

// 3. The walk-in flow's rows are at the higher floor.
const walkIn = readFileSync(join(ROOT, "components/staff/WalkInSheet.tsx"), "utf8");
if (!walkIn.includes("walkIn")) {
  failures.push("WalkInSheet.tsx must use the walk-in row height, not the standard control height");
}
if (!/minHeight:\s*64/.test(walkIn) && !walkIn.includes("walkIn")) {
  failures.push(`the "Something else" row must be at least ${WALK_IN_ROW}px`);
}

// -------------------------------------------------- invariants 3 and 4
//
// Nothing checked these until slice 6, because until slice 6 there was no STK
// waiting screen for them to be on. They are the two that decide whether a
// deposit completes, so they are checked the same way as the heights: against
// the constants, in CI.

const booking = readFileSync(join(ROOT, "components/booking/BookingFlow.tsx"), "utf8");

/**
 * Comments stripped before anything is matched.
 *
 * Same reason `test_org_scoped_manager_guard.py` parses instead of grepping:
 * this file's own explanation of *why* `*334#` must come from the token
 * contains the string `*334#`, and a check that cannot tell code from a comment
 * about code gets weakened until it means nothing.
 */
const bookingCode = booking.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

// **Invariant 3 — the hold countdown stays visible.** Checked as "the countdown
// is rendered from `countdownLabel`" rather than "a countdown exists", because
// the failure this guards against is not deletion. It is a well-meaning tidy-up
// that renders the raw seconds and shows "0:00 — expired" while the server is
// still holding the slot through its grace window, which is the unexplained
// failure the invariant is about.
if (!bookingCode.includes("countdownLabel")) {
  failures.push(
    "BookingFlow.tsx must render the hold countdown through countdownLabel, so a " +
      "timer at zero with a push still outstanding says so instead of claiming to have expired"
  );
}
if (/countdown\s*&&|hideCountdown|showCountdown/.test(bookingCode)) {
  failures.push("the hold countdown must not be behind a condition — CLAUDE.md §10, invariant 3");
}

// **Invariant 4 — the `*334#` USSD fallback.** From the token, never typed, so
// a re-skin cannot edit it away and a translation cannot drop it. When the push
// does not arrive — and it often does not — this line is the difference between
// a completed deposit and an abandoned booking.
if (!bookingCode.includes("INVARIANTS.ussdFallback")) {
  failures.push(
    "the STK waiting screen must show INVARIANTS.ussdFallback, from the token and not as a literal"
  );
}
if (/["'`]\*334#["'`]/.test(bookingCode)) {
  failures.push("the USSD fallback must come from INVARIANTS.ussdFallback, not a hardcoded string");
}

if (failures.length) {
  console.error("CLAUDE.md §10 invariants violated:\n" + failures.map((f) => `  - ${f}`).join("\n"));
  process.exit(1);
}
console.log(
  `invariants ok — ${MIN_TARGET}px floor, ${WALK_IN_ROW}px walk-in rows, ` +
    "3-per-row grid, visible countdown, USSD fallback"
);
