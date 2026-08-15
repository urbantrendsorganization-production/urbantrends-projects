/**
 * The widget's structural checks. Runs in CI, after the build.
 *
 * Three separate jobs, and they are separate on purpose:
 *
 * 1. **The boundary.** `booking-core` has `check-no-framework.mjs` because a
 *    framework import creeps in one convenience at a time. This package has the
 *    same problem one layer down: `view.ts` will want `document` the first time
 *    somebody needs to measure something, and once it has it the view is no
 *    longer testable without a DOM and the tests quietly stop being written.
 *
 * 2. **CLAUDE.md §10, in the widget.** `web/scripts/check-invariants.mjs`
 *    proves the standalone screens honour the four; `packages/tokens/src/check.mjs`
 *    proves they ship as constants. Neither can see this package, and this
 *    package is the one that runs inside a host page — which is the situation
 *    the invariants were written for in the first place.
 *
 * 3. **The shipped file.** The checks above read source. This one reads the
 *    built bundle, because everything between the two — a define that did not
 *    apply, a minifier that folded a constant away, a stylesheet that was never
 *    inlined — is invisible from the source side and would ship a widget with
 *    no palette and no floor.
 *
 * Failing is the point.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { join } from "node:path";

const PKG = new URL("..", import.meta.url).pathname;
const SRC = join(PKG, "src");
const BUNDLE = join(PKG, "..", "..", "public", "widget", "booknasi.js");
const STYLESHEET = join(PKG, "..", "..", "public", "widget", "stylesheet.css");
const TOKENS_TS = join(PKG, "..", "tokens", "dist", "tokens.ts");

/** The two files allowed a browser. Everything else is testable without one. */
const IMPURE = new Set(["mount.ts", "index.ts"]);

const GLOBALS = [
  /\bdocument\b/,
  /\bwindow\b/,
  /\blocalStorage\b/,
  /\bsessionStorage\b/,
  /\bnavigator\b/,
  /(?<![.\w])fetch\s*\(/,
  /\bsetInterval\b/,
  /\bsetTimeout\b/,
];

/** A budget, not a guess. See the note where it is asserted. */
const MAX_GZIPPED_BYTES = 20 * 1024;

const failures = [];
const fail = (message) => failures.push(message);

function sources(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) out.push(...sources(path));
    else if (path.endsWith(".ts") && !path.endsWith(".test.ts")) out.push(path);
  }
  return out;
}

/** Comments out, strings kept.
 *
 *  Strings are kept because half of what is checked here *is* a string — the
 *  literal `*334#`, the word "deposit". Comments go because every subject below
 *  is discussed at length in the prose above it, and a check that cannot tell
 *  code from a comment about code gets weakened until it means nothing. Same
 *  lesson as `check-no-framework.mjs`. */
function code(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

/** Interpolations replaced by `0`, so an expression spliced into a template is
 *  not read as text the client sees — and so `min-height: ${...}px` still
 *  parses as a length rather than as a bare unit. */
function flattened(source) {
  return source.replace(/\$\{[^{}]*\}/g, "0");
}

// ------------------------------------------------------------- 1. boundary

for (const file of sources(SRC)) {
  const name = file.slice(SRC.length + 1);
  if (IMPURE.has(name)) continue;
  const stripped = code(readFileSync(file, "utf8"));
  for (const pattern of GLOBALS) {
    const match = stripped.match(pattern);
    if (match) {
      fail(`${name}: uses \`${match[0]}\` — only ${[...IMPURE].join(" and ")} may touch a browser`);
    }
  }
  if (/["']react|["']next/.test(stripped)) fail(`${name}: imports a framework`);
}

// ---------------------------------------------------- 2. CLAUDE.md §10, here

const css = code(readFileSync(join(SRC, "css.ts"), "utf8"));
const view = code(readFileSync(join(SRC, "view.ts"), "utf8"));
const config = readFileSync(join(SRC, "config.ts"), "utf8");
const tokens = readFileSync(TOKENS_TS, "utf8");

/* Invariants 1 and 2, read off the resolved stylesheet rather than the source.
   `build.mjs` evaluates css.ts and writes the real CSS out, because the source
   is a template literal — `min-height: ${INVARIANTS.minTargetHeightPx}px` — and
   the 52 is nowhere near the rule until it runs. Checking the source proves the
   constant is referenced; checking this proves the rule that ships. */
let sheet = "";
try {
  sheet = readFileSync(STYLESHEET, "utf8");
} catch {
  fail(`no stylesheet at ${STYLESHEET} — run \`npm run widget\` first`);
}

if (sheet) {
  /* Invariant 1 — the floor, in pixels.
     `rem` is a multiple of the *host page's* root font size. A host running
     `html { font-size: 12px }` would shrink every target in the widget to 39px,
     with the invariant still correct in the token file and still wrong on the
     screen. */
  const heights = [...sheet.matchAll(/min-height:\s*([^;]+);/g)].map((m) => m[1].trim());
  if (!heights.length) fail("the stylesheet declares no min-height — nothing carries the floor");
  for (const height of heights) {
    if (/\b(rem|em|%|vh|vw|ch)\b/.test(height)) {
      fail(`stylesheet: min-height "${height}" is relative; the target floor must be px`);
    }
    const px = Number(height.replace("px", ""));
    if (Number.isFinite(px) && px < 52) {
      fail(`stylesheet: min-height ${height} is below the 52px floor — CLAUDE.md §10, invariant 1`);
    }
  }
  if (!heights.includes("52px")) fail("no rule in the stylesheet sets the 52px floor");

  /* Invariant 2 — three per row. */
  if (!/grid-template-columns:\s*repeat\(3,/.test(sheet)) {
    fail("the slot grid is not three per row — CLAUDE.md §10, invariant 2");
  }

  /* No token can express either of them, so no host stylesheet can reach them. */
  if (/--bn-(min-target|target-height|slots-per-row|ussd)/.test(sheet)) {
    fail("the §10 invariants must never become CSS custom properties");
  }
  if (!sheet.includes("--bn-accent:")) fail("the stylesheet carries no palette");
}

/* And in the source: taken from the constants, never written as numbers. */
if (!css.includes("INVARIANTS.minTargetHeightPx")) {
  fail("css.ts must take the target floor from INVARIANTS.minTargetHeightPx, not a literal 52");
}
if (!css.includes("INVARIANTS.slotsPerRow")) {
  fail("css.ts must take the slot grid's columns from INVARIANTS.slotsPerRow");
}
if (/repeat\(\s*[0-9]/.test(css)) fail("the slot grid's column count must not be a literal");

/* Invariant 3 — the countdown is never conditional.
   Checked as "rendered through countdownLabel and behind no flag", because the
   failure is not deletion. It is a tidy-up that renders raw seconds and shows
   "0:00 — expired" while the server is still holding the slot through its grace
   window, which is precisely the unexplained failure the invariant names. */
if (!view.includes("countdownLabel")) {
  fail("view.ts must render the countdown through countdownLabel, not a raw number");
}
for (const pattern of [/hideCountdown/, /showCountdown/, /countdown\s*&&/, /waitingPanel\s*&&/]) {
  if (pattern.test(view)) fail("the hold countdown must not sit behind a condition — §10, invariant 3");
}

/* Invariant 4 — the USSD fallback, from the constant. */
if (!view.includes("INVARIANTS.ussdFallback")) {
  fail("the waiting screen must render INVARIANTS.ussdFallback");
}
if (/["'`]\*334#["'`]/.test(view)) fail("the USSD fallback must come from the constant, not a literal");

/* None of the four may be expressible as a custom property, anywhere. */
for (const source of [css, view, config]) {
  if (/--bn-(min-target|target-height|slots-per-row|ussd)/.test(source)) {
    fail("the §10 invariants must never become CSS custom properties — a host stylesheet reaches those");
  }
}

/* Exactly one `.bn-root`, and the view does not render it.
   The token scope carries the host's overrides as inline properties, set by
   mount.ts on the container. A second `.bn-root` inside the rendered tree
   redeclares the whole palette from the stylesheet and shadows them — a widget
   that mounts correctly and silently ignores every option it was given, which
   is what happened the first time this was wired up. */
if (/bn-root/.test(view)) {
  fail("view.ts must render .bn-screen, not .bn-root — .bn-root is the mount container's token scope");
}
if (!/className\s*=\s*"bn-root"/.test(readFileSync(join(SRC, "mount.ts"), "utf8"))) {
  fail("mount.ts must put .bn-root on the container it sets the host's overrides on");
}

/* The refund and forfeit sentence: relabellable, never removable. */
if (!view.includes("refundSentence")) {
  fail("view.ts must render refundSentence — the terms are read before the money moves, CLAUDE.md §5");
}
if (/refundSentence\s*&&|showTerms|hideTerms/.test(view)) {
  fail("the refund sentence must not sit behind a condition");
}

/* "deposit" is a copy token. The neutral-widget mock relabels it "reservation
   fee"; a host is entitled to. So the word must not be written into any string
   the client reads — it arrives through `config.copy`. */
const literals = flattened(view).match(/'[^'\n]*'|"[^"\n]*"|`[^`]*`/g) ?? [];
for (const literal of literals) {
  if (/deposit/i.test(literal)) {
    fail(`view.ts: ${literal.trim()} hardcodes a copy token — it must come from config.copy`);
  }
}

/* Screen 8 promises no automatic refund. Nothing automatic exists, the money is
   with the shop rather than with us, and a promise the product cannot keep is
   the worst thing to put on the one screen where the client is already unhappy.
   CLAUDE.md §12 records the decision; the standalone app carries the same test. */
if (/automatic(ally)?[^.]{0,40}refund|refund[^.]{0,40}automatic/i.test(flattened(view))) {
  fail("screen 8 must not promise an automatic refund — CLAUDE.md §12");
}

/* Every host option maps to a token the palette actually defines. Two lists in
   two packages, and a mismatch is invisible: the widget renders, the option
   does nothing, and the host concludes it is not themeable. */
const overridable = new Set([...tokens.matchAll(/"(--bn-[a-z-]+)"/g)].map((match) => match[1]));
for (const [, property] of config.matchAll(/:\s*"(--bn-[a-z-]+)"/g)) {
  if (!overridable.has(property)) {
    fail(`config.ts offers ${property}, which is not in the tokens package's HOST_OVERRIDABLE`);
  }
}

// --------------------------------------------------------- 3. the built file

let bundle = "";
try {
  bundle = readFileSync(BUNDLE, "utf8");
} catch {
  fail(`no bundle at ${BUNDLE} — run \`npm run widget\` first`);
}

if (bundle) {
  /* The tokens really were inlined. `css.ts` falls back to an empty string when
     the define is absent, which is right for the tests and a catastrophe in a
     shipped file: every colour would resolve to nothing. */
  if (!bundle.includes("--bn-accent:")) {
    fail("the built bundle carries no palette — the tokens define did not apply");
  }
  /* The constants survived bundling at the values the stylesheet interpolates.
     A minifier that folded one of these to the wrong number would leave a
     stylesheet.css that is correct and a shipped widget that is not. */
  for (const [name, value] of [
    ["minTargetHeightPx", "52"],
    ["slotsPerRow", "3"],
  ]) {
    if (!bundle.includes(`${name}:${value}`)) {
      fail(`the built bundle does not carry ${name}=${value}`);
    }
  }
  if (!bundle.includes("*334#")) fail("the built bundle has lost the *334# fallback line");

  /* A budget. The client arrives cold from a WhatsApp link on 3G and the
     design's success measure is sixty seconds to a paid deposit; the widget is
     the first thing on that clock. This number exists so that adding a date
     library or a validation package is a decision somebody has to argue for,
     rather than something noticed a year later in a page-weight audit. */
  const gzipped = gzipSync(Buffer.from(bundle)).length;
  if (gzipped > MAX_GZIPPED_BYTES) {
    fail(
      `the bundle is ${(gzipped / 1024).toFixed(1)} kB gzipped, over the ` +
        `${MAX_GZIPPED_BYTES / 1024} kB budget. See the note in check-widget.mjs.`,
    );
  }
}

if (failures.length) {
  console.error("widget checks FAILED:\n" + failures.map((line) => `  - ${line}`).join("\n"));
  process.exit(1);
}
console.log(
  "widget ok — boundary held, 52px floor in px, 3-per-row grid, countdown unconditional, " +
    "*334# from the constant, deposit is a copy token, terms present",
);
