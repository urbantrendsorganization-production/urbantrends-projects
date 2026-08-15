/**
 * The widget's stylesheet, as a string, for a shadow root.
 *
 * ## Why the shadow root is the right container for CLAUDE.md §10
 *
 * The four invariants have to survive an arbitrary host page. A host stylesheet
 * saying `#booking button { height: 36px }` is not malice — it is a designer
 * making their own site consistent, and it lands on the one screen where a
 * mis-tap books the wrong time. Inside a shadow root that rule cannot select
 * anything: host selectors do not cross the boundary.
 *
 * What *does* cross is custom property inheritance, and that is the half the
 * design wants — it is how a host restyles the widget at all. So the boundary
 * is not a wall, it is a valve: selectors out, named values in. That happens to
 * be exactly the shape CLAUDE.md §10 describes, which is why the widget is a
 * shadow root and not an iframe (an iframe blocks the values too, and then the
 * host cannot theme anything) and not a plain div (which blocks nothing).
 *
 * One consequence worth being explicit about: `.bn-root` below **redefines**
 * every `--bn-*` token inside the shadow root, so a value inherited from the
 * host page is shadowed rather than used. The host's overrides therefore do not
 * arrive by inheritance at all — `mount.ts` sets the ones `config.ts` accepted
 * as inline properties on that same element, where they win. That is
 * deliberate: it means the *only* way a host reaches a token is through the
 * named list, and a host who sets `--bn-space-gutter` on their container
 * changes nothing.
 *
 * The corollary cost a working re-skin once and is now a rule: **exactly one
 * element carries `.bn-root`, and the view never renders it.** A second one
 * inside the tree redeclares the whole palette from this stylesheet and
 * shadows the inline overrides on the first, which looks like a widget that
 * mounted correctly and ignored every option it was given. The view renders
 * `.bn-screen` instead, and `check-widget.mjs` refuses the class in view.ts.
 *
 * ## Why the invariant sizes are px
 *
 * `min-height: 52px`, never `3.25rem`. `rem` is a multiple of the host page's
 * root font size, so a host running `html { font-size: 12px }` — which is a
 * real thing sites do — would silently shrink every target in the widget to
 * 39 px. The invariant would still be in the code, still be in the token file,
 * and still be wrong on the screen. `check-widget.mjs` fails the build if a
 * relative unit appears in the rules that carry the floor.
 */

import { INVARIANTS } from "@booknasi/tokens";

/**
 * The token declarations, inlined by the build from `@booknasi/tokens`'s
 * generated CSS. See `scripts/build.mjs`.
 *
 * `typeof` rather than a bare read, because the tests import this module
 * without a bundler and the constant does not exist there. The empty fallback
 * is safe in tests and would be a catastrophe in a shipped bundle — every
 * colour would resolve to nothing — so `check-widget.mjs` asserts the built
 * file actually contains the palette rather than trusting the define to have
 * been applied.
 */
declare const __BN_TOKENS_CSS__: string;
const TOKENS = typeof __BN_TOKENS_CSS__ === "string" ? __BN_TOKENS_CSS__ : "";

export function stylesheet(): string {
  return `${TOKENS}\n${WIDGET}`;
}

const WIDGET = `
/* The host element. \`all: initial\` stops the page's font size, colour and
   line height from being inherited across the boundary. It is not sufficient on
   its own — a host rule with an id selector outscores \`:host\` — which is why
   .bn-root below sets the same things again, from inside, where no host
   selector can reach. */
:host { all: initial; display: block; contain: content; }

/* The token scope, and the *only* element the host's overrides are set on —
   mount.ts puts them here as inline properties. The rendered tree below must
   never carry this class: the patcher rebuilds attributes on every draw, so an
   inline style on a rendered node would be wiped a second later, and a second
   .bn-root would redeclare every token and shadow the host's values outright.
   That is not hypothetical — it is the bug this split fixes. */
.bn-root {
  display: block;
  font-family: var(--bn-font-ui);
  font-size: var(--bn-text-body-size);
  line-height: var(--bn-text-body-leading);
  color: var(--bn-ink);
  background: var(--bn-canvas);
  text-align: left;
}
.bn-root *, .bn-root *::before, .bn-root *::after { box-sizing: border-box; }
.bn-root p, .bn-root h1, .bn-root h2 { margin: 0; }
.bn-root button { font: inherit; color: inherit; margin: 0; }

/* What the view renders into. The design's rule: the client flow caps at ~480px
   and centres. Inside a host container it must survive whatever width it is
   given, so this is a max and never a width. */
.bn-screen {
  display: block;
  max-width: 480px;
  margin: 0 auto;
  padding: var(--bn-space-7) var(--bn-space-gutter) var(--bn-space-11);
  box-sizing: border-box;

  /* Card and panel radii, derived from the one radius a host may set.
     \`--bn-radius-md\` is the only radius on the tokens package's overridable
     list, and using \`--bn-radius-card\` directly for cards meant a host asking
     for square corners got square buttons inside 14px cards — the option
     half-applied, which is worse than not offering it. The ratios reproduce
     the design's 12/14/16 exactly at the default and collapse to zero together,
     so "square corners" — the design's own neutral-widget mock — is reachable
     with the one lever §10 names. Scoped here rather than on .bn-root so the
     token defaults are untouched for every other consumer. */
  --bn-radius-card: calc(var(--bn-radius-md) * 7 / 6);
  --bn-radius-panel: calc(var(--bn-radius-md) * 4 / 3);
}

.bn-stack { display: grid; gap: var(--bn-space-7); }
.bn-stack-tight { display: grid; gap: var(--bn-space-5); }
.bn-row { display: flex; gap: var(--bn-space-5); align-items: baseline; }
.bn-grow { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.bn-fixed { flex-shrink: 0; }

.bn-shop { color: var(--bn-ink-45); font-size: var(--bn-text-body-sm-size); }
.bn-title {
  font-family: var(--bn-font-display);
  font-size: var(--bn-text-title-size);
  line-height: var(--bn-text-title-leading);
  letter-spacing: var(--bn-text-title-tracking);
  font-weight: 700;
}
.bn-label {
  font-size: var(--bn-text-label-size);
  letter-spacing: var(--bn-text-label-tracking);
  /* Host-overridable, per CLAUDE.md §10's list. The design's neutral-widget
     mock uses uppercase 0.22em labels; the BookNasi default is uppercase too,
     and a host that wants sentence case sets --bn-label-case: none. */
  text-transform: var(--bn-label-case, uppercase);
  color: var(--bn-ink-45);
}
.bn-mono { font-family: var(--bn-font-mono); font-variant-numeric: tabular-nums; }
.bn-muted { color: var(--bn-ink-45); }
.bn-note { color: var(--bn-ink-70); font-size: var(--bn-text-body-sm-size); line-height: 1.5; }
.bn-strong { font-weight: 600; }
.bn-big { font-size: var(--bn-text-money-size); font-weight: 600; }

.bn-card {
  padding: var(--bn-space-7);
  border-radius: var(--bn-radius-card);
  background: var(--bn-surface);
  border: 1.5px solid var(--bn-border);
}
.bn-panel { padding: var(--bn-space-7); border-radius: var(--bn-radius-panel); }
.bn-panel-pay { background: var(--bn-pay-50); color: var(--bn-pay-700); }
.bn-panel-hold { background: var(--bn-hold-50); color: var(--bn-hold-700); }
.bn-panel-fail { background: var(--bn-fail-50); color: var(--bn-fail-700); }
.bn-panel-info { background: var(--bn-info-50); color: var(--bn-info-700); }
.bn-empty {
  padding: var(--bn-space-11);
  border: 1.5px dashed var(--bn-border);
  border-radius: var(--bn-radius-panel);
  color: var(--bn-ink-45);
  text-align: center;
}

/* ------------------------------------------------- CLAUDE.md §10, invariant 1
   52px, in px, on every control. Staff use this standing and one-handed; a
   client uses it on a phone on 3G with one thumb. Nothing here is a rem. */
.bn-target {
  min-height: ${INVARIANTS.minTargetHeightPx}px;
  display: flex;
  align-items: center;
  gap: var(--bn-space-5);
  width: 100%;
  text-align: left;
  padding: var(--bn-space-6) var(--bn-space-7);
  border-radius: var(--bn-radius-md);
  border: 1.5px solid var(--bn-border);
  background: var(--bn-surface);
  color: var(--bn-ink);
  font-size: var(--bn-text-body-lg-size);
  cursor: pointer;
}
.bn-target:focus-visible {
  outline: 2px solid var(--bn-accent);
  outline-offset: 2px;
  box-shadow: 0 0 0 4px var(--bn-clay-50);
}
/* Selection is tint plus a 2px border, never a second filled accent button —
   the design's accent discipline: one accent-filled control per screen, and it
   is the one that moves the booking forward. */
.bn-target[aria-pressed="true"] {
  background: var(--bn-clay-50);
  border: 2px solid var(--bn-accent);
}
.bn-card-target { display: block; padding: var(--bn-space-7); border-radius: var(--bn-radius-card); }

.bn-cta {
  min-height: ${INVARIANTS.minTargetHeightPx}px;
  width: 100%;
  border: none;
  border-radius: var(--bn-radius-md);
  background: var(--bn-accent);
  color: var(--bn-surface);
  font-size: var(--bn-text-body-lg-size);
  font-weight: 600;
  padding: var(--bn-space-6);
  cursor: pointer;
}
.bn-cta:active { background: var(--bn-accent-pressed); transform: scale(0.985); }
.bn-cta[disabled] {
  background: var(--bn-line);
  color: var(--bn-ink-disabled);
  cursor: default;
  transform: none;
}
.bn-secondary { background: var(--bn-surface); color: var(--bn-ink); border: 1.5px solid var(--bn-border); }
.bn-secondary[disabled] { background: var(--bn-surface); opacity: 0.6; }

/* ------------------------------------------------- CLAUDE.md §10, invariant 2
   Three per row. Denser raises mis-taps on the screen where a mis-tap books the
   wrong time; wider pushes the afternoon below the fold. */
.bn-slots {
  display: grid;
  grid-template-columns: repeat(${INVARIANTS.slotsPerRow}, minmax(0, 1fr));
  gap: var(--bn-space-4);
}
.bn-slot {
  min-height: ${INVARIANTS.minTargetHeightPx}px;
  display: grid;
  place-items: center;
  padding: 0 var(--bn-space-3);
  border-radius: var(--bn-radius-md);
  border: 1.5px solid var(--bn-border);
  background: var(--bn-surface);
  color: var(--bn-ink);
  font-family: var(--bn-font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 15.5px;
  cursor: pointer;
}
.bn-slot[aria-pressed="true"] { background: var(--bn-accent); color: var(--bn-surface); border-color: var(--bn-accent); }

.bn-days { display: flex; gap: var(--bn-space-4); overflow-x: auto; padding-bottom: var(--bn-space-6); }
.bn-day {
  min-height: ${INVARIANTS.minTargetHeightPx}px;
  min-width: 60px;
  flex-shrink: 0;
  display: grid;
  place-items: center;
  padding: 0 var(--bn-space-5);
  border-radius: var(--bn-radius-md);
  border: 1.5px solid var(--bn-border);
  background: var(--bn-surface);
  color: var(--bn-ink);
  cursor: pointer;
}
.bn-day[aria-pressed="true"] { background: var(--bn-ink); color: var(--bn-surface); border-color: var(--bn-ink); }

.bn-pill {
  padding: 2px var(--bn-space-4);
  border-radius: var(--bn-radius-pill);
  background: var(--bn-clay-50);
  color: var(--bn-clay-700);
  font-size: var(--bn-text-body-sm-size);
}
.bn-line { display: flex; justify-content: space-between; gap: var(--bn-space-5); padding: var(--bn-space-3) 0; }

.bn-phone { display: flex; align-items: stretch; }
.bn-phone-prefix {
  min-height: ${INVARIANTS.minTargetHeightPx}px;
  display: flex;
  align-items: center;
  padding: 0 var(--bn-space-6);
  border: 1.5px solid var(--bn-border);
  border-right: none;
  border-radius: var(--bn-radius-md) 0 0 var(--bn-radius-md);
  color: var(--bn-ink-45);
  font-family: var(--bn-font-mono);
}
.bn-phone-input {
  flex: 1;
  min-width: 0;
  min-height: ${INVARIANTS.minTargetHeightPx}px;
  padding: 0 var(--bn-space-6);
  border: 1.5px solid var(--bn-border);
  border-radius: 0 var(--bn-radius-md) var(--bn-radius-md) 0;
  background: var(--bn-surface);
  color: var(--bn-ink);
  font-family: var(--bn-font-mono);
  font-size: var(--bn-text-body-lg-size);
}
.bn-phone-input:focus-visible { outline: 2px solid var(--bn-accent); outline-offset: -2px; }

/* ------------------------------------------------- CLAUDE.md §10, invariant 3
   The hold countdown. No rule in this file hides it, and there is no modifier
   class that could — see the note in view.ts. The track is the one element
   under the 52px floor: it is aria-hidden, unreachable by any user by any
   means, and a 52px bar across the screen would obstruct the thing the floor
   exists to keep usable. */
.bn-track { margin-top: var(--bn-space-5); height: 6px; border-radius: 999px; background: var(--bn-track); overflow: hidden; }
.bn-track-fill { height: 100%; background: var(--bn-hold-600); transition: width 1s linear; }
@media (prefers-reduced-motion: reduce) {
  .bn-track-fill { transition: none; }
  .bn-cta:active { transform: none; }
}

.bn-link { color: var(--bn-ink); font-family: var(--bn-font-mono); }
.bn-error { margin-bottom: var(--bn-space-7); font-size: var(--bn-text-body-size); }
`;
