/**
 * Everything a host site is allowed to say, and the shape of the refusal when
 * it says something else.
 *
 * CLAUDE.md §10 draws the line: a host may override accent, surface, canvas,
 * border, radius, fonts and label casing, and may relabel "deposit" itself
 * because money words are copy tokens. It may not touch the 52 px target floor,
 * the three-per-row slot grid, the visible hold countdown, or the `*334#`
 * fallback line.
 *
 * ## Why the line is drawn here rather than in the stylesheet
 *
 * The tokens package already makes the four invariants constants instead of
 * custom properties, so no host *stylesheet* can reach them. This file closes
 * the other door: a host does not hand us CSS, it hands us a small map of named
 * options, and the names are a fixed list. There is no key that reaches an
 * invariant because there is no key that reaches anything not on the list —
 * `data-min-target="20px"` is not refused by a rule about targets, it is
 * refused because it is not a name this file knows.
 *
 * That is the difference between a policy and a filter. A filter has to
 * anticipate what will be attacked; this has to anticipate what will be
 * *offered*, which is a list we wrote.
 *
 * ## What is conspicuously not on the list: ink
 *
 * Surfaces are themeable and text colour is not, which is why a dark host site
 * gets a light widget panel rather than a dark one — and which is what the
 * design's own neutral-widget mock shows. It looks like an oversight and is
 * not: a host who can set ink can set it to the surface colour, and at that
 * point the refund and forfeit sentence that CLAUDE.md §10 says may be
 * translated or relabelled **but never removed** is removable, invisibly, with
 * one hex value and complete deniability. Contrast is the last thing standing
 * between "the terms are on the screen" and "the terms are on the screen in
 * white on white", so it is not a lever we hand out.
 *
 * ## Why unknown keys warn instead of throwing
 *
 * A typo — `data-acent` — must not take the booking widget off a shop's page.
 * The widget renders, unstyled by that option, and says what it ignored on the
 * console. Failing loudly at the network boundary is right; failing loudly at
 * the branding boundary means a misspelling costs a shop its Saturday.
 *
 * ## No colour parsing, and why that is safe
 *
 * Values are applied with `element.style.setProperty`, which puts them through
 * the CSSOM: a value the parser rejects is simply not set, and there is no
 * string concatenation into a stylesheet anywhere in this widget for an
 * injected `;` to escape from. The check below is therefore about clarity
 * rather than safety — a host that writes something structural gets told, in
 * the console, instead of watching the option silently do nothing.
 */

import { COPY, HOST_OVERRIDABLE, type HostOverride } from "@booknasi/tokens";

export interface WidgetConfig {
  /** The shop's public slug. The only genuinely required option. */
  slug: string;
  /** Origin of the API. `https://api.booknasi.co.ke`, or "" for same-origin. */
  apiBase: string;
  /** Custom property to value. Keys are always drawn from `HOST_OVERRIDABLE`. */
  theme: Partial<Record<HostOverride, string>>;
  /** The one word a host is most likely to want changed. */
  copy: { deposit: string; depositTitleCase: string };
}

export interface ParseResult {
  config: WidgetConfig | null;
  /** Why the widget did not mount. Empty when `config` is set. */
  errors: string[];
  /** What was ignored. Never fatal. */
  warnings: string[];
}

/**
 * `data-` attribute to the custom property it sets.
 *
 * The whole host styling surface, in one object. Adding a row is a decision
 * about what a host may change; there is no wildcard and no passthrough, which
 * is what makes the invariants unreachable rather than merely undocumented.
 */
const THEME_KEYS: Record<string, HostOverride> = {
  accent: "--bn-accent",
  "accent-pressed": "--bn-accent-pressed",
  surface: "--bn-surface",
  canvas: "--bn-canvas",
  border: "--bn-border",
  "font-display": "--bn-font-display",
  "font-ui": "--bn-font-ui",
  radius: "--bn-radius-md",
  "label-case": "--bn-label-case",
};

/** Not styling: where to mount, what to call, and the one copy token. */
const OTHER_KEYS = ["shop", "api", "target", "deposit-word"];

/** Structural characters. See the note on `setProperty` above — this is for
 *  the host's benefit, not ours. */
const STRUCTURAL = /[;{}<>]|url\s*\(|@import/i;

export function parseConfig(options: Record<string, string | undefined>): ParseResult {
  const errors: string[] = [];
  const warnings: string[] = [];

  const slug = (options.shop ?? "").trim();
  if (!slug) {
    errors.push('No shop. Add data-shop="your-shop-slug" to the script tag.');
  } else if (!/^[a-z0-9][a-z0-9-]*$/.test(slug)) {
    // Matched against the slug rule rather than sent and allowed to 404,
    // because the failure a host will actually make is pasting the whole
    // booking URL into the attribute, and "404" is a poor way to say that.
    errors.push(`"${slug}" is not a shop slug. Use the last part of the booking link.`);
  }

  const apiBase = (options.api ?? "").trim().replace(/\/$/, "");
  if (apiBase && !/^https?:\/\/[^\s/]+$/i.test(apiBase)) {
    errors.push(`data-api must be an http(s) origin, not "${apiBase}".`);
  }

  const theme: Partial<Record<HostOverride, string>> = {};
  for (const [name, value] of Object.entries(options)) {
    if (value === undefined || value.trim() === "") continue;
    const property = THEME_KEYS[name];
    if (!property) {
      if (!OTHER_KEYS.includes(name)) warnings.push(`Ignored data-${name}: not an option.`);
      continue;
    }
    if (STRUCTURAL.test(value)) {
      warnings.push(`Ignored data-${name}: a value, not a rule.`);
      continue;
    }
    theme[property] = value.trim();
  }

  const deposit = (options["deposit-word"] ?? "").trim() || COPY.deposit;

  return {
    config: errors.length ? null : { slug, apiBase, theme, copy: copyFor(deposit) },
    errors,
    warnings,
  };
}

/**
 * The copy token in both casings the screens need.
 *
 * Title case is derived rather than asked for separately: a host relabelling
 * "deposit" as "reservation fee" should not also have to supply "Reservation
 * fee", and one of the two going unset is how a screen ends up reading
 * "Deposit now KES 1,000" beside "your reservation fee is refunded".
 */
function copyFor(deposit: string): WidgetConfig["copy"] {
  return {
    deposit,
    depositTitleCase: deposit.charAt(0).toUpperCase() + deposit.slice(1),
  };
}

/**
 * Proof, at runtime, that the theme map cannot express an invariant.
 *
 * `HOST_OVERRIDABLE` is the tokens package's list and `THEME_KEYS` is this
 * file's; they are written in two places and must agree. Checked here rather
 * than only in a test because the failure — a key that maps to a property
 * nothing defines — is invisible: the widget renders, the option does nothing,
 * and the host concludes the widget is not themeable.
 */
export function themeKeysAreValid(): string[] {
  const allowed = new Set<string>(HOST_OVERRIDABLE);
  return Object.entries(THEME_KEYS)
    .filter(([, property]) => !allowed.has(property))
    .map(([name, property]) => `data-${name} maps to ${property}, which no token defines`);
}

/** The host-facing names, for the error message and for the demo page. */
export const OPTION_NAMES = [...OTHER_KEYS, ...Object.keys(THEME_KEYS)];

/**
 * A script tag's attributes, as options.
 *
 * `<script data-shop="x" data-accent="#111">` becomes `{shop, accent}`. Here
 * rather than in `index.ts` because it is the only part of the one-tag
 * integration with a decision in it — which attributes count, and what their
 * names become — and `index.ts` is a file no test can reach.
 *
 * Everything that is not `data-` is skipped, so `src`, `async`, `defer`,
 * `crossorigin`, `integrity` and whatever else a host's tag manager decorates
 * the tag with never reaches `parseConfig` and never produces a warning about
 * an option nobody was trying to set.
 */
export function optionsFromAttributes(
  attributes: Iterable<{ name: string; value: string }>,
): Record<string, string> {
  const options: Record<string, string> = {};
  for (const { name, value } of attributes) {
    if (name.startsWith("data-")) options[name.slice(5)] = value;
  }
  return options;
}
