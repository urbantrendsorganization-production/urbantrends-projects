/**
 * The entry point, and the whole integration contract:
 *
 * ```html
 * <script src="https://booknasi.co.ke/widget/booknasi.js"
 *         data-shop="mint-braids-kilimani"
 *         data-api="https://api.booknasi.co.ke"></script>
 * ```
 *
 * One tag, no build step, no npm install, no framework on the host's side. That
 * is the bar, because CLAUDE.md §1's second front door is a `/site` template
 * whose client never sees BookNasi at all — and the person pasting this in may
 * be the shop owner's cousin with a Squarespace login. Anything that needs a
 * bundler on their side is a widget that does not get installed.
 *
 * ## Where it renders
 *
 * In order: the element named by `data-target`, then the first
 * `[data-booknasi]` on the page, then a container inserted where the script tag
 * itself sits. The last one is what makes the one-tag case work — paste the tag
 * where the booking form should be, and that is where it appears.
 *
 * ## What it puts on `window`
 *
 * One name, `BookNasi`, with one method. A host that wants control — a modal,
 * a tab, two shops on one page — calls `BookNasi.mount(element, options)` and
 * gets a handle with `destroy()`. Everything else the widget owns lives inside
 * its shadow root, and it registers no custom element: a custom element name is
 * a global that can collide exactly once and then never be fixed.
 *
 * ## Failure is visible, and it is visible to the right person
 *
 * A missing `data-shop` writes one line to the console and renders nothing. It
 * does not throw: an uncaught error from a third-party script can take out the
 * host page's own scripts, and taking down a salon's website because their
 * booking widget is misconfigured is a much worse outcome than a booking widget
 * that is not there.
 */

import {
  type ParseResult,
  type WidgetConfig,
  optionsFromAttributes,
  parseConfig,
  themeKeysAreValid,
} from "./config";
import { type Mounted, mount as mountInto } from "./mount";

const PREFIX = "[BookNasi]";

export interface MountOptions extends Record<string, string | undefined> {
  shop?: string;
  api?: string;
}

/** The public API. `options` uses the same names as the `data-` attributes. */
export function mount(target: Element | string, options: MountOptions): Mounted | null {
  const element = typeof target === "string" ? document.querySelector(target) : target;
  if (!element) {
    console.error(`${PREFIX} No element matched ${String(target)}.`);
    return null;
  }
  const parsed = parseConfig(options);
  report(parsed);
  if (!parsed.config) return null;
  return mountInto(element, parsed.config);
}

function report({ errors, warnings }: ParseResult) {
  for (const error of errors) console.error(`${PREFIX} ${error}`);
  for (const warning of warnings) console.warn(`${PREFIX} ${warning}`);
  // A mismatch between this package's option list and the tokens package's is
  // not something a host can cause or fix, so it is warned about here and never
  // fatal. `check-widget.mjs` fails the build on it, which is where it belongs.
  for (const problem of themeKeysAreValid()) console.warn(`${PREFIX} ${problem}`);
}

function containerFor(script: HTMLElement, target: string | undefined): Element | null {
  if (target) return document.querySelector(target);
  const declared = document.querySelector("[data-booknasi]");
  if (declared) return declared;
  // Inserted where the tag is, so the widget lands where it was pasted. The
  // script tag itself stays put; removing it would break a host that reads its
  // own DOM, and it costs nothing to leave.
  const made = document.createElement("div");
  script.parentNode?.insertBefore(made, script);
  return made;
}

function auto() {
  const script = document.currentScript as HTMLElement | null;
  if (!script) return;
  const options: MountOptions = optionsFromAttributes(Array.from(script.attributes));
  // No `data-shop` at all means the host loaded the bundle to call `mount`
  // themselves. That is a supported way to use this and must not be scolded.
  if (!options.shop) return;
  const container = containerFor(script, options.target);
  if (!container) {
    console.error(`${PREFIX} No element matched data-target="${options.target}".`);
    return;
  }
  const parsed = parseConfig(options);
  report(parsed);
  if (parsed.config) mountInto(container, parsed.config);
}

declare global {
  interface Window {
    BookNasi?: { mount: typeof mount };
  }
}

if (typeof window !== "undefined") {
  window.BookNasi = { mount };
  try {
    auto();
  } catch (error) {
    // See the header. The host's own page is not ours to break.
    console.error(`${PREFIX} Could not start.`, error);
  }
}

export type { Mounted, WidgetConfig };
