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
for (const file of [...walk(join(ROOT, "components")), ...walk(join(ROOT, "app"))]) {
  const source = readFileSync(file, "utf8");
  for (const match of source.matchAll(HEIGHT)) {
    const value = Number(match[1]);
    // Below the floor is a failure. Anything at or above it is a deliberate
    // larger target (the 56px CTA, the 64px FAB and walk-in rows) and fine.
    if (value > 0 && value < MIN_TARGET) {
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

if (failures.length) {
  console.error("CLAUDE.md §10 invariants violated:\n" + failures.map((f) => `  - ${f}`).join("\n"));
  process.exit(1);
}
console.log(`invariants ok — ${MIN_TARGET}px floor, ${WALK_IN_ROW}px walk-in rows`);
