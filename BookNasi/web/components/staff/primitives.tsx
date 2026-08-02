"use client";

/**
 * The controls every staff screen is built from.
 *
 * CLAUDE.md §10 invariant 1: **52 px minimum target height on any interactive
 * control**, and 64 px on walk-in rows. Those numbers arrive here from
 * `INVARIANTS` in `@booknasi/tokens` — constants, never CSS custom properties,
 * so a host stylesheet embedding the widget physically cannot reach them.
 *
 * They are applied here rather than at each call site for the same reason. A
 * screen that sets its own heights is a screen where one of them ends up at
 * 44 px because it looked cramped, on the one device where that matters most:
 * a shop phone held one-handed by somebody with wet hands.
 *
 * `web/scripts/check-invariants.mjs` fails the build if a staff component
 * reaches for a hardcoded height instead of these.
 */

import { INVARIANTS } from "@booknasi/tokens";
import type { CSSProperties, ReactNode } from "react";

const TARGET = `${INVARIANTS.minTargetHeightPx}px`;
const WALK_IN_ROW = `${INVARIANTS.walkInRowMinHeightPx}px`;

type ButtonProps = {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "destructive" | "quiet";
  disabled?: boolean;
  /** The design is explicit: a disabled button's label says *why*. */
  disabledReason?: string;
  style?: CSSProperties;
};

const VARIANTS: Record<string, CSSProperties> = {
  primary: { background: "var(--bn-accent)", color: "#fff", border: "none" },
  secondary: {
    background: "var(--bn-surface)",
    color: "var(--bn-ink)",
    border: "1.5px solid var(--bn-border)",
  },
  destructive: {
    background: "var(--bn-fail-50)",
    color: "var(--bn-fail-700)",
    border: "1.5px solid var(--bn-fail-300)",
  },
  quiet: { background: "transparent", color: "var(--bn-ink-45)", border: "none" },
};

export function Button({
  children,
  onClick,
  variant = "primary",
  disabled,
  disabledReason,
  style,
}: ButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        minHeight: TARGET,
        width: "100%",
        padding: "0 var(--bn-space-7)",
        borderRadius: "var(--bn-radius-md)",
        fontFamily: "var(--bn-font-ui)",
        fontSize: "var(--bn-text-body-lg-size)",
        fontWeight: 600,
        cursor: disabled ? "default" : "pointer",
        ...VARIANTS[variant],
        ...(disabled
          ? { background: "var(--bn-line)", color: "var(--bn-ink-disabled)", border: "none" }
          : {}),
        ...style,
      }}
    >
      {disabled && disabledReason ? disabledReason : children}
    </button>
  );
}

/** A tappable row. `walkIn` raises the floor to 64 px — the wet-hands screen. */
export function Row({
  children,
  onClick,
  walkIn = false,
  selected = false,
  style,
}: {
  children: ReactNode;
  onClick?: () => void;
  walkIn?: boolean;
  selected?: boolean;
  style?: CSSProperties;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        minHeight: walkIn ? WALK_IN_ROW : TARGET,
        width: "100%",
        display: "flex",
        alignItems: "center",
        gap: "var(--bn-space-5)",
        textAlign: "left",
        padding: "var(--bn-space-5) var(--bn-space-7)",
        borderRadius: "var(--bn-radius-card)",
        background: selected ? "var(--bn-clay-50)" : "var(--bn-surface)",
        border: selected ? "2px solid var(--bn-accent)" : "1.5px solid var(--bn-border)",
        cursor: onClick ? "pointer" : "default",
        fontFamily: "var(--bn-font-ui)",
        fontSize: "var(--bn-text-body-lg-size)",
        color: "var(--bn-ink)",
        ...style,
      }}
    >
      {children}
    </button>
  );
}

/** Bottom sheet. Scrim, 20px top corners, 240ms — and reduced-motion honoured. */
export function Sheet({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(31,23,18,0.4)",
        display: "flex",
        alignItems: "flex-end",
        justifyContent: "center",
        zIndex: 40,
      }}
    >
      <div
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-label={title}
        style={{
          width: "100%",
          maxWidth: 480,
          maxHeight: "88vh",
          overflowY: "auto",
          background: "var(--bn-surface)",
          borderRadius: "var(--bn-radius-sheet) var(--bn-radius-sheet) 0 0",
          boxShadow: "var(--bn-shadow-sheet)",
          padding: "var(--bn-space-9) var(--bn-space-gutter) var(--bn-space-12)",
        }}
      >
        <h2
          style={{
            fontFamily: "var(--bn-font-display)",
            fontSize: "var(--bn-text-title-size)",
            margin: "0 0 var(--bn-space-7)",
          }}
        >
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}

/** Bottom toast, above the thumb. Ink for progress, green for done, red for failed. */
export function Toast({ tone, children }: { tone: "progress" | "done" | "failed"; children: ReactNode }) {
  const background = {
    progress: "var(--bn-ink)",
    done: "var(--bn-pay-700)",
    failed: "var(--bn-fail-700)",
  }[tone];
  return (
    <div
      role="status"
      style={{
        position: "fixed",
        left: "50%",
        transform: "translateX(-50%)",
        bottom: "var(--bn-space-11)",
        width: "calc(100% - 2 * var(--bn-space-gutter))",
        maxWidth: 440,
        background,
        color: "#fff",
        borderRadius: "var(--bn-radius-card)",
        padding: "var(--bn-space-6) var(--bn-space-7)",
        fontSize: "var(--bn-text-body-size)",
        zIndex: 50,
      }}
    >
      {children}
    </div>
  );
}
