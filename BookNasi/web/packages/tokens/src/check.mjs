#!/usr/bin/env node
/**
 * Structural checks on the generated tokens. Runs in CI.
 *
 * The one that matters is the override chain: a host must be able to set
 * `--bn-accent` on the mount container and have it reach every component. That
 * only works if the literal hex sits on the semantic name and the palette name
 * aliases to it. Getting this backwards produces a file that looks correct,
 * builds cleanly, and silently ignores every host override.
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "..", "dist", "tokens.css"), "utf8");
const ts = readFileSync(join(here, "..", "dist", "tokens.ts"), "utf8");
const tokens = JSON.parse(readFileSync(join(here, "tokens.json"), "utf8"));

const failures = [];
const check = (ok, message) => {
  if (!ok) failures.push(message);
};

/* The override chain. */
for (const [name, def] of Object.entries(tokens.color)) {
  if (name.startsWith("$") || !def.host || !def.hostName || def.hostName === name) continue;
  check(
    css.includes(`--bn-${def.hostName}: ${def.value};`),
    `--bn-${def.hostName} must carry the literal ${def.value}, so a host override sits at the root of the chain`,
  );
  check(
    css.includes(`--bn-${name}: var(--bn-${def.hostName});`),
    `--bn-${name} must alias to var(--bn-${def.hostName}), or Tailwind's ${name} will ignore host overrides`,
  );
}

/* Scoping. A bare :root would leak the palette into the host page. */
check(css.includes(".bn-root {"), "tokens.css must scope its variables to .bn-root");
check(!/^:root\s*\{/m.test(css), "tokens.css must never declare variables on bare :root");

/* Invariants are constants, not variables. */
for (const key of ["minTargetHeightPx", "slotsPerRow", "ussdFallback"]) {
  check(ts.includes(key), `INVARIANTS must export ${key}`);
}
check(
  !css.includes("--bn-slots-per-row") && !css.includes("--bn-min-target"),
  "the CLAUDE.md §10 invariants must not be expressible as CSS custom properties",
);
check(
  ts.includes('"*334#"'),
  "the *334# fallback must be a constant — it is the difference between a completed deposit and an abandoned booking",
);

/* The design-canvas colour must not have shipped. */
check(
  !css.includes("#EFE7DE"),
  "#EFE7DE is the design-canvas background, not a product surface. It must stay out of tokens.css",
);

/* The scales were deliberately collapsed; guard against them creeping back. */
check(!css.includes("--bn-space-13:"), "the spacing scale is 12 steps; 9px folded into 10, 13 into 14");
check(
  Object.keys(tokens.radius).filter((k) => !k.startsWith("$")).length === 8,
  "the radius scale is 8 named roles, not the export's overlapping numeric ranges",
);

if (failures.length) {
  console.error("tokens check FAILED:");
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log(`tokens check: ${Object.keys(tokens.color).length - 0} colours, override chain intact`);
