// GENERATED from src/tokens.json by src/build.mjs — do not edit.

/**
 * CLAUDE.md §10. These are not CSS custom properties and must never become
 * them. A host embedding the widget can restyle everything else; these four
 * are the difference between a payment that completes and one that does not,
 * so they are constants that a stylesheet cannot reach.
 */
export const INVARIANTS = {
  /** Minimum interactive target. Staff use this standing, one-handed, wet. */
  minTargetHeightPx: 52,
  /** Walk-in rows go further: the wet-hands screen. */
  walkInRowMinHeightPx: 64,
  /** Denser grids raise mis-taps on the screen where a mis-tap books the wrong time. */
  slotsPerRow: 3,
  /** The only reason it is safe to ask a client to leave the page. Never hide it. */
  holdCountdownAlwaysVisible: true,
  /** When the STK push does not arrive — and it often does not. */
  ussdFallback: "*334#",
};

/** Overridable by a host site at runtime, by setting these on the mount container. */
export const HOST_OVERRIDABLE = [
  "--bn-accent",
  "--bn-accent-pressed",
  "--bn-surface",
  "--bn-canvas",
  "--bn-border",
  "--bn-font-display",
  "--bn-font-ui",
  "--bn-radius-md",
  "--bn-label-case"
];

/** Copy tokens. "deposit" reads wrong next to a luxury salon; "reservation fee" does not. */
export const COPY = {
  deposit: "deposit",
  depositTitleCase: "Deposit",
};
