/**
 * The host's whole surface area, and the shape of every refusal.
 *
 * The tests that matter here are the negative ones. A host cannot reach the
 * four invariants in CLAUDE.md §10, cannot reach text colour, and cannot get a
 * value with structure in it as far as the stylesheet — and none of those are
 * visible by reading `parseConfig`, because they are all things it does *not*
 * do.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { OPTION_NAMES, optionsFromAttributes, parseConfig, themeKeysAreValid } from "./config";

test("a shop slug is the only thing a host must supply", () => {
  const { config, errors } = parseConfig({ shop: "mint-braids-kilimani" });

  assert.equal(errors.length, 0);
  assert.equal(config?.slug, "mint-braids-kilimani");
});

test("no shop is an error, and the error says what to add", () => {
  const { config, errors } = parseConfig({});

  assert.equal(config, null);
  assert.match(errors[0], /data-shop/);
});

test("a pasted booking URL is caught as a bad slug rather than sent and 404d", () => {
  const { config, errors } = parseConfig({ shop: "https://booknasi.co.ke/book/mint-braids" });

  assert.equal(config, null);
  assert.match(errors[0], /not a shop slug/);
});

test("the api origin must be an origin", () => {
  assert.equal(parseConfig({ shop: "a", api: "javascript:alert(1)" }).config, null);
  assert.equal(parseConfig({ shop: "a", api: "https://api.booknasi.co.ke" }).errors.length, 0);
});

test("a trailing slash on the api origin is not a double slash on every path", () => {
  const { config } = parseConfig({ shop: "a", api: "https://api.booknasi.co.ke/" });

  assert.equal(config?.apiBase, "https://api.booknasi.co.ke");
});

test("no api means same-origin, which is what the standalone page wants", () => {
  assert.equal(parseConfig({ shop: "a" }).config?.apiBase, "");
});

test("the styling options map to custom properties", () => {
  const { config } = parseConfig({ shop: "a", accent: "#111", radius: "0px", "label-case": "none" });

  assert.deepEqual(config?.theme, {
    "--bn-accent": "#111",
    "--bn-radius-md": "0px",
    "--bn-label-case": "none",
  });
});

test("an unknown option is a warning and not a dead widget", () => {
  const { config, warnings } = parseConfig({ shop: "a", acent: "#111" });

  // A typo must not take the booking widget off a shop's page.
  assert.ok(config);
  assert.match(warnings[0], /acent/);
});

test("target and deposit-word are options, not typos", () => {
  const { warnings } = parseConfig({ shop: "a", target: "#here", "deposit-word": "booking fee" });

  assert.deepEqual(warnings, []);
});

// ------------------------------------------- CLAUDE.md §10, from the outside

test("there is no option that reaches the 52px target floor", () => {
  const { config, warnings } = parseConfig({
    shop: "a",
    "min-target": "20px",
    "target-height": "20px",
    "min-target-height": "20",
  });

  assert.deepEqual(config?.theme, {});
  assert.equal(warnings.length, 3);
});

test("there is no option that reaches the three-per-row grid", () => {
  const { config } = parseConfig({ shop: "a", "slots-per-row": "6", slots: "6", grid: "6" });

  assert.deepEqual(config?.theme, {});
});

test("there is no option that reaches the countdown or the USSD line", () => {
  const { config } = parseConfig({
    shop: "a",
    countdown: "hidden",
    "hide-countdown": "true",
    ussd: "",
    "ussd-fallback": "*111#",
  });

  assert.deepEqual(config?.theme, {});
});

test("there is no option that reaches text colour", () => {
  // Not an oversight — see the note in config.ts. A host who can set ink can
  // set it to the surface colour, and the refund sentence §10 forbids removing
  // becomes removable by making it invisible.
  const { config } = parseConfig({ shop: "a", ink: "#fff", color: "#fff", text: "#fff" });

  assert.deepEqual(config?.theme, {});
});

test("the option list is closed, so a new one is a decision somebody made", () => {
  assert.deepEqual(
    [...OPTION_NAMES].sort(),
    [
      "accent",
      "accent-pressed",
      "api",
      "border",
      "canvas",
      "deposit-word",
      "font-display",
      "font-ui",
      "label-case",
      "radius",
      "shop",
      "surface",
      "target",
    ].sort(),
  );
});

test("a value with structure in it is refused with a reason", () => {
  const { config, warnings } = parseConfig({ shop: "a", accent: "red; } .bn-track { display:none" });

  assert.deepEqual(config?.theme, {});
  assert.match(warnings[0], /a value, not a rule/);
});

test("a font family with quotes and commas is not structure", () => {
  const { config } = parseConfig({ shop: "a", "font-ui": "'Jost', system-ui, sans-serif" });

  assert.equal(config?.theme["--bn-font-ui"], "'Jost', system-ui, sans-serif");
});

test("every offered property is one the tokens package actually defines", () => {
  // Two lists in two packages. A mismatch renders fine and does nothing, which
  // is the failure a host reports as "your widget is not themeable".
  assert.deepEqual(themeKeysAreValid(), []);
});

// --------------------------------------------------------- the copy token

test("relabelling the deposit relabels it in both casings", () => {
  const { config } = parseConfig({ shop: "a", "deposit-word": "reservation fee" });

  assert.equal(config?.copy.deposit, "reservation fee");
  assert.equal(config?.copy.depositTitleCase, "Reservation fee");
});

test("no relabel leaves the token's own word", () => {
  assert.equal(parseConfig({ shop: "a" }).config?.copy.deposit, "deposit");
});

test("an empty relabel is not a blank word on the screen", () => {
  assert.equal(parseConfig({ shop: "a", "deposit-word": "   " }).config?.copy.deposit, "deposit");
});

// ------------------------------------------------- the one-tag integration

test("a script tag's data- attributes become the options", () => {
  const options = optionsFromAttributes([
    { name: "src", value: "https://booknasi.co.ke/widget/booknasi.js" },
    { name: "data-shop", value: "mint-braids-kilimani" },
    { name: "data-accent", value: "#111" },
    { name: "data-deposit-word", value: "booking fee" },
  ]);

  assert.deepEqual(options, {
    shop: "mint-braids-kilimani",
    accent: "#111",
    "deposit-word": "booking fee",
  });
});

test("everything a tag manager decorates the tag with is ignored silently", () => {
  // `async`, `crossorigin`, `integrity`, `nonce`. None of these are attempts to
  // set an option, so none of them should warn about one.
  const options = optionsFromAttributes([
    { name: "src", value: "x.js" },
    { name: "async", value: "" },
    { name: "crossorigin", value: "anonymous" },
    { name: "integrity", value: "sha384-abc" },
    { name: "nonce", value: "r4nd0m" },
    { name: "data-shop", value: "mint-braids" },
  ]);

  assert.deepEqual(options, { shop: "mint-braids" });
  assert.deepEqual(parseConfig(options).warnings, []);
});

test("the tag's options go through the same parse as a scripted mount", () => {
  const { config, warnings } = parseConfig(
    optionsFromAttributes([
      { name: "data-shop", value: "mint-braids" },
      { name: "data-acent", value: "#111" },
    ]),
  );

  assert.equal(config?.slug, "mint-braids");
  assert.match(warnings[0], /acent/);
});
