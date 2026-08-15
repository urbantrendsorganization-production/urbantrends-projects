/**
 * One file, no runtime dependencies, served from a `<script>` tag.
 *
 * ## Why there is a bundler here at all
 *
 * CLAUDE.md §11 says not to take a dependency for something the stdlib or the
 * framework already does. Nothing in this repo bundles a library: Next builds
 * pages, `tsc` emits modules, and neither produces a single self-contained file
 * a stranger can paste into a Squarespace site. Native ES modules would avoid
 * the tool and pay for it in round trips — six imports resolved one after
 * another on a 3G connection, before the first service name appears, on the
 * screen whose success measure is sixty seconds from link to paid deposit.
 *
 * So: esbuild, one devDependency, a single binary, no config file and no
 * plugin. It does the two things needed — resolve and minify — and if it ever
 * has to go, what replaces it has to satisfy this same twenty lines.
 *
 * ## Why the tokens are inlined rather than fetched
 *
 * A second request for a stylesheet is a second thing that can be blocked by a
 * host's Content-Security-Policy, a second round trip, and a window in which
 * the widget is rendered and unstyled inside somebody else's design. The CSS is
 * about 4 kB and compresses to almost nothing next to that.
 *
 * The inlining is done with a `define` rather than a loader plugin so that
 * `css.ts` stays a plain TypeScript module the tests can import.
 */

import { gzipSync } from "node:zlib";
import { copyFileSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import * as esbuild from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));
const pkg = join(here, "..");
const web = join(pkg, "..", "..");
const outDir = join(web, "public", "widget");

const tokensCss = join(web, "packages", "tokens", "dist", "tokens.css");
try {
  statSync(tokensCss);
} catch {
  console.error(
    "widget: packages/tokens/dist/tokens.css is missing. Run `npm run tokens` first —\n" +
      "        a bundle built without it would ship with no palette at all.",
  );
  process.exit(1);
}

mkdirSync(outDir, { recursive: true });

const result = await esbuild.build({
  entryPoints: [join(pkg, "src", "index.ts")],
  outfile: join(outDir, "booknasi.js"),
  bundle: true,
  minify: true,
  // An IIFE, not an ES module: `document.currentScript` is null inside a module
  // script, and the one-tag integration in `index.ts` reads its own attributes
  // off it. A host who wants a module can still call `BookNasi.mount`.
  format: "iife",
  // The floor is the Android phone this product is actually opened on, not the
  // laptop it is written on. Optional chaining and `??` are transpiled.
  target: ["es2019"],
  legalComments: "none",
  define: {
    __BN_TOKENS_CSS__: JSON.stringify(readFileSync(tokensCss, "utf8")),
  },
  metafile: true,
});

copyFileSync(join(pkg, "demo", "host.html"), join(outDir, "demo.html"));

/**
 * The stylesheet, resolved.
 *
 * `css.ts` is a template literal, so in the shipped bundle `min-height` reads
 * `${k.minTargetHeightPx}px` and the 52 does not appear anywhere near it. That
 * makes the invariants unassertable from the built file by string matching, and
 * matching a minified file for `52` would pass on any 52 in the program.
 *
 * So the module is built a second time, as CommonJS, evaluated here, and its
 * output written out as real CSS. `check-widget.mjs` then reads a stylesheet
 * rather than a guess about one — which is the difference between "the source
 * mentions the constant" and "the rule that ships says 52px". It is also a
 * genuinely useful artefact: a host debugging a re-skin can read it.
 */
const compiled = await esbuild.build({
  entryPoints: [join(pkg, "src", "css.ts")],
  bundle: true,
  format: "cjs",
  platform: "node",
  write: false,
  define: { __BN_TOKENS_CSS__: JSON.stringify(readFileSync(tokensCss, "utf8")) },
});
const module_ = { exports: {} };
new Function("module", "exports", compiled.outputFiles[0].text)(module_, module_.exports);
writeFileSync(join(outDir, "stylesheet.css"), module_.exports.stylesheet());

const bytes = statSync(join(outDir, "booknasi.js")).size;
const gzipped = gzipSync(readFileSync(join(outDir, "booknasi.js"))).length;
writeFileSync(join(outDir, "meta.json"), JSON.stringify({ bytes, gzipped }, null, 2));

if (result.warnings.length) {
  for (const warning of result.warnings) console.warn(`widget: ${warning.text}`);
}
console.log(
  `widget: public/widget/booknasi.js — ${(bytes / 1024).toFixed(1)} kB, ` +
    `${(gzipped / 1024).toFixed(1)} kB gzipped`,
);
