/**
 * The structural half of this package's whole reason to exist.
 *
 * `booking-core` holds the client booking flow so that slice 10's widget is a
 * second *renderer* and not a second *implementation*. That only stays true if
 * nothing in `src/` reaches for a framework — and it will be reached for, one
 * convenient import at a time, by somebody who only needs `useState` "just
 * here". So it is asserted rather than trusted, and it fails the build.
 *
 * Three things are refused:
 *
 * 1. **Framework imports.** React, Next, and anything that only exists inside
 *    one of them.
 * 2. **Browser globals.** `window`, `document`, `localStorage`, a bare
 *    `fetch`. The widget may run where these differ or are proxied, and the
 *    tests here run in Node with none of them. `transport.ts` takes `fetchImpl`
 *    as a parameter for exactly this reason.
 * 3. **Timers.** `setInterval` and `setTimeout` own a resource the host page
 *    has opinions about. The countdown is driven by the renderer calling
 *    `tick()`; this package computes seconds from a timestamp and no more.
 *
 * Parsed line by line with comments and strings stripped, because a test that
 * cannot tell code from a comment about code gets weakened until it means
 * nothing — the same lesson slice 3 learned about `all_objects`, and the reason
 * this file's own prose can say `window` without failing itself.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const SRC = new URL("../src", import.meta.url).pathname;

const FORBIDDEN_IMPORTS = [/["']react["']/, /["']react-dom/, /["']next\//, /["']next["']/];
const FORBIDDEN_GLOBALS = [
  /\bwindow\b/,
  /\bdocument\b/,
  /\blocalStorage\b/,
  /\bsessionStorage\b/,
  /\bnavigator\b/,
  // A bare call, not the injected `fetchImpl` parameter.
  /(?<![.\w])fetch\s*\(/,
  /\bsetInterval\b/,
  /\bsetTimeout\b/,
];

function sources(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) out.push(...sources(path));
    else if (path.endsWith(".ts") && !path.endsWith(".test.ts")) out.push(path);
  }
  return out;
}

/** Strip block comments, line comments and string literals. */
function code(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/(["'`])(?:\\.|(?!\1)[^\\])*\1/g, '""');
}

const failures = [];
for (const file of sources(SRC)) {
  const raw = readFileSync(file, "utf8");
  const stripped = code(raw);
  const name = file.slice(SRC.length + 1);

  for (const pattern of FORBIDDEN_IMPORTS) {
    // Imports are checked against the raw text: the module specifier is a
    // string literal, and stripping strings would remove the thing being
    // looked for. Narrowed to import/require lines so prose is unaffected.
    for (const line of raw.split("\n")) {
      if (!/^\s*(import|export)\b.*\bfrom\b|require\s*\(/.test(line)) continue;
      if (pattern.test(line)) failures.push(`${name}: imports a framework — ${line.trim()}`);
    }
  }
  for (const pattern of FORBIDDEN_GLOBALS) {
    const match = stripped.match(pattern);
    if (match) failures.push(`${name}: uses \`${match[0]}\`, which the widget may not have`);
  }
}

if (failures.length) {
  console.error(
    "booking-core must stay framework-free — see packages/booking-core/README.md:\n" +
      failures.map((f) => `  - ${f}`).join("\n")
  );
  process.exit(1);
}
console.log(`booking-core: ${sources(SRC).length} modules, no framework, no globals, no timers`);
