#!/usr/bin/env node
/**
 * Emits tokens.css, tokens.ts and tailwind.js from tokens.json.
 *
 * No dependencies on purpose — this runs in CI before anything is installed,
 * and a token pipeline that needs a build toolchain to produce three text files
 * is a liability.
 *
 * The important output is tokens.css. Every variable is declared under
 * `.bn-root`, never bare `:root`:
 *
 *   - the standalone app puts `.bn-root` on <html>
 *   - the widget puts it on its own mount container
 *
 * A bare `:root` in the widget bundle would leak BookNasi's palette into the
 * host page, and would make host overrides a specificity fight.
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const tokens = JSON.parse(
  await import("node:fs").then((fs) => fs.readFileSync(join(here, "tokens.json"), "utf8")),
);

const isMeta = (k) => k.startsWith("$");
const val = (v) => (v && typeof v === "object" && "value" in v ? v.value : v);

/* ------------------------------------------------------------------ CSS -- */

const lines = [];
const hostLines = [];

/**
 * Host-overridable tokens are declared semantic-name-first, with the palette
 * name aliasing to it:
 *
 *   --bn-accent: #C2521F;
 *   --bn-clay-600: var(--bn-accent);
 *
 * and not the other way round. Tailwind maps `clay-600` to `var(--bn-clay-600)`,
 * so if the literal lived on `--bn-clay-600` a host setting `--bn-accent` would
 * change nothing. The override has to sit at the root of the chain, not on a
 * leaf that nothing reads.
 */
const emit = (name, value, meta) => {
  if (meta && meta.host && meta.hostName && meta.hostName !== name) {
    lines.push(`  --bn-${meta.hostName}: ${value};`);
    lines.push(`  --bn-${name}: var(--bn-${meta.hostName});`);
    hostLines.push(`  --bn-${meta.hostName}`);
    return;
  }
  lines.push(`  --bn-${name}: ${value};`);
  if (meta && meta.host) hostLines.push(`  --bn-${name}`);
};

for (const [name, def] of Object.entries(tokens.color)) {
  if (isMeta(name)) continue;
  emit(name, val(def), def);
}

lines.push("");
for (const [name, def] of Object.entries(tokens.font)) {
  if (isMeta(name)) continue;
  emit(`font-${name}`, val(def), def);
}

lines.push("");
for (const [name, t] of Object.entries(tokens.type)) {
  if (isMeta(name)) continue;
  lines.push(`  --bn-text-${name}-size: ${t.size};`);
  lines.push(`  --bn-text-${name}-leading: ${t.lineHeight};`);
  if (t.tracking) lines.push(`  --bn-text-${name}-tracking: ${t.tracking};`);
}

lines.push("");
for (const [name, v] of Object.entries(tokens.space)) {
  if (isMeta(name)) continue;
  lines.push(`  --bn-space-${name}: ${v};`);
}

lines.push("");
for (const [name, def] of Object.entries(tokens.radius)) {
  if (isMeta(name)) continue;
  emit(`radius-${name}`, val(def), def);
}

lines.push("");
for (const [name, v] of Object.entries(tokens.shadow)) {
  if (isMeta(name)) continue;
  lines.push(`  --bn-shadow-${name}: ${v};`);
}

lines.push("");
for (const [name, v] of Object.entries(tokens.target)) {
  if (isMeta(name)) continue;
  lines.push(`  --bn-target-${name}: ${v};`);
}

// The one copy token that is expressible in CSS. A host with uppercase,
// wide-tracked labels sets this; the words themselves come from COPY in
// tokens.ts, because they are strings, not styling.
lines.push("");
lines.push(`  --bn-label-case: ${tokens.label.case.value};`);
hostLines.push("  --bn-label-case");

const css = `/* GENERATED from src/tokens.json by src/build.mjs — do not edit. */
/* Scoped to .bn-root, never :root. See build.mjs for why. */

.bn-root {
${lines.join("\n")}
}

/* A host embedding the widget overrides these, and only these, by setting them
   on the mount container:
${hostLines.join("\n")}
   Everything else is BookNasi's own.

   The four invariants in CLAUDE.md §10 are deliberately absent from this file.
   They live in tokens.ts as constants so no stylesheet can reach them. */

@media (prefers-reduced-motion: reduce) {
  /* Step changes and sheets cross-fade instead of sliding; the countdown bar
     still animates, because it is information, not decoration. */
  .bn-root * {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
  .bn-root [data-bn-countdown] {
    transition-duration: revert !important;
  }
}
`;

/* ------------------------------------------------------------------- TS -- */

const inv = tokens.invariants;
const ts = `// GENERATED from src/tokens.json by src/build.mjs — do not edit.

/**
 * CLAUDE.md §10. These are not CSS custom properties and must never become
 * them. A host embedding the widget can restyle everything else; these four
 * are the difference between a payment that completes and one that does not,
 * so they are constants that a stylesheet cannot reach.
 */
export const INVARIANTS = {
  /** Minimum interactive target. Staff use this standing, one-handed, wet. */
  minTargetHeightPx: ${inv.minTargetHeightPx},
  /** Walk-in rows go further: the wet-hands screen. */
  walkInRowMinHeightPx: ${inv.walkInRowMinHeightPx},
  /** Denser grids raise mis-taps on the screen where a mis-tap books the wrong time. */
  slotsPerRow: ${inv.slotsPerRow},
  /** The only reason it is safe to ask a client to leave the page. Never hide it. */
  holdCountdownAlwaysVisible: ${inv.holdCountdownAlwaysVisible},
  /** When the STK push does not arrive — and it often does not. */
  ussdFallback: ${JSON.stringify(inv.ussdFallback)},
} as const;

/** Overridable by a host site at runtime, by setting these on the mount container. */
export const HOST_OVERRIDABLE = ${JSON.stringify(
  hostLines.map((l) => l.trim()),
  null,
  2,
)} as const;

export type HostOverride = (typeof HOST_OVERRIDABLE)[number];

/** Copy tokens. "deposit" reads wrong next to a luxury salon; "reservation fee" does not. */
export const COPY = {
  deposit: ${JSON.stringify(tokens.label.deposit.value)},
  depositTitleCase: ${JSON.stringify(tokens.label["deposit-title-case"].value)},
} as const;
`;

/* -------------------------------------------------------------- tailwind -- */

const twColors = {};
for (const [name, def] of Object.entries(tokens.color)) {
  if (isMeta(name)) continue;
  twColors[name] = `var(--bn-${name})`;
}
const twRadius = {};
for (const [name, def] of Object.entries(tokens.radius)) {
  if (isMeta(name)) continue;
  twRadius[name] = `var(--bn-radius-${name})`;
}
const twSpace = {};
for (const [name, v] of Object.entries(tokens.space)) {
  if (isMeta(name)) continue;
  twSpace[name] = `var(--bn-space-${name})`;
}

const tailwind = `// GENERATED from src/tokens.json by src/build.mjs — do not edit.
//
// Every value maps to a CSS variable rather than a literal hex. This is the
// whole reason the widget can inherit a host's colours: \`bg-clay-600\`
// compiled to #C2521F could never be overridden at runtime, but
// \`background: var(--bn-clay-600)\` can.

module.exports = {
  theme: {
    extend: {
      colors: ${JSON.stringify(twColors, null, 6).replace(/\n/g, "\n      ")},
      borderRadius: ${JSON.stringify(twRadius, null, 6).replace(/\n/g, "\n      ")},
      spacing: ${JSON.stringify(twSpace, null, 6).replace(/\n/g, "\n      ")},
      fontFamily: {
        display: "var(--bn-font-display)",
        ui: "var(--bn-font-ui)",
        mono: "var(--bn-font-mono)",
      },
    },
  },
};
`;

const dist = join(root, "dist");
mkdirSync(dist, { recursive: true });
writeFileSync(join(dist, "tokens.css"), css);
writeFileSync(join(dist, "tokens.ts"), ts);
writeFileSync(join(dist, "tailwind.js"), tailwind);

// Plain JS alongside the TypeScript, so that Node can `require` this package
// directly. Next resolves it through a tsconfig path and never needs this, but
// the slice 5 test runner (`node --test` on tsc output) does, and so would any
// non-TypeScript consumer of the widget. Generated by stripping the type
// annotations rather than by running tsc: adding a compiler to the tokens
// package to emit forty lines of constants would be a dependency for nothing.
const js = ts
  .replace(/^export type .*$/gm, "")
  .replace(/ as const;/g, ";")
  .replace(/^(export const [A-Z_]+) = /gm, "$1 = ")
  .replace(/\n{3,}/g, "\n\n");
writeFileSync(join(dist, "tokens.js"), js);

const count = lines.filter((l) => l.trim().startsWith("--bn-")).length;
console.log(`tokens: ${count} custom properties, ${hostLines.length + 1} host-overridable`);
console.log(`        ${Object.keys(inv).length} invariants emitted as constants, not variables`);
