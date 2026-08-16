"use client";

/**
 * The controls the setup screen is built from.
 *
 * Separate from `components/staff/primitives.tsx` because the two screens have
 * genuinely different jobs, not because the file was long. The staff
 * primitives are for a phone held one-handed with wet hands: full-width rows,
 * one action per screen, 64 px targets. This is a settings surface an owner
 * opens on a laptop and works down — labelled fields, tables, several things
 * editable at once.
 *
 * What does *not* differ is CLAUDE.md §10's floor. Every interactive control
 * here is 52 px, from `INVARIANTS.minTargetHeightPx`, for the same reason it is
 * everywhere else: an owner adding services on a shop phone during a quiet ten
 * minutes is the normal case, not the exception. `Button` is imported from the
 * staff primitives rather than redrawn, so there is one primary button in the
 * product and it cannot drift.
 *
 * `web/scripts/check-invariants.mjs` walks this directory and fails the build
 * on a hardcoded height below the floor.
 */

import { INVARIANTS } from "@booknasi/tokens";
import type { CSSProperties, ReactNode } from "react";

export { Button } from "../staff/primitives";

const TARGET = `${INVARIANTS.minTargetHeightPx}px`;

/** The shared resting shape of every text-entry control on this screen. */
const CONTROL: CSSProperties = {
  minHeight: TARGET,
  width: "100%",
  padding: "0 var(--bn-space-6)",
  borderRadius: "var(--bn-radius-md)",
  border: "1.5px solid var(--bn-border)",
  background: "var(--bn-surface)",
  color: "var(--bn-ink)",
  fontFamily: "var(--bn-font-ui)",
  fontSize: "var(--bn-text-body-size)",
};

export function Section({
  id,
  title,
  intro,
  children,
  actions,
}: {
  id?: string;
  title: string;
  intro?: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section
      id={id}
      style={{
        background: "var(--bn-surface)",
        border: "1px solid var(--bn-line)",
        borderRadius: "var(--bn-radius-card)",
        padding: "var(--bn-space-8)",
        display: "grid",
        gap: "var(--bn-space-7)",
      }}
    >
      <header
        style={{
          display: "flex",
          gap: "var(--bn-space-6)",
          alignItems: "baseline",
          justifyContent: "space-between",
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "grid", gap: "var(--bn-space-3)" }}>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--bn-font-display)",
              fontSize: "var(--bn-text-title-size)",
            }}
          >
            {title}
          </h2>
          {intro ? (
            <p style={{ margin: 0, color: "var(--bn-ink-70)", textWrap: "pretty" }}>{intro}</p>
          ) : null}
        </div>
        {actions}
      </header>
      {children}
    </section>
  );
}

export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: ReactNode;
  error?: string;
  children: ReactNode;
}) {
  return (
    <label style={{ display: "grid", gap: "var(--bn-space-3)", minWidth: 0 }}>
      <span
        style={{
          fontSize: "var(--bn-text-label-size)",
          letterSpacing: "var(--bn-text-label-tracking)",
          textTransform: "uppercase",
          color: "var(--bn-ink-45)",
        }}
      >
        {label}
      </span>
      {children}
      {error ? (
        <span style={{ color: "var(--bn-fail-700)", fontSize: "var(--bn-text-body-sm-size)" }}>
          {error}
        </span>
      ) : hint ? (
        <span style={{ color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
          {hint}
        </span>
      ) : null}
    </label>
  );
}

export function TextInput({
  value,
  onChange,
  placeholder,
  mono = false,
  type = "text",
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  mono?: boolean;
  //: `password` is for the M-Pesa secrets. Not to stop the owner reading what
  //: they are typing — they need to, it is a paste from the Safaricom portal —
  //: but because a salon laptop is a shared screen with a counter in front of
  //: it, and a passkey left visible in a form is a passkey anyone at the
  //: counter can photograph.
  type?: "text" | "url" | "time" | "password";
}) {
  return (
    <input
      type={type}
      value={value}
      placeholder={placeholder}
      onChange={(event) => onChange(event.target.value)}
      style={{ ...CONTROL, ...(mono ? { fontFamily: "var(--bn-font-mono)" } : {}) }}
    />
  );
}

/**
 * Whole numbers, and empty is a real state.
 *
 * `<input type="number">` with a React number value fights the user the moment
 * they clear the box to retype: the value round-trips through `Number("")`,
 * becomes `NaN` or `0`, and the field either refuses to empty or silently
 * fills with a zero the owner did not type. A price of 0 and a price nobody
 * has typed yet are different things — one of them is a free service — so the
 * value stays a string here and is parsed at submit.
 */
export function NumberInput({
  value,
  onChange,
  placeholder,
  prefix,
  suffix,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  prefix?: string;
  suffix?: string;
}) {
  const affix: CSSProperties = {
    minHeight: TARGET,
    display: "flex",
    alignItems: "center",
    padding: "0 var(--bn-space-5)",
    background: "var(--bn-canvas)",
    border: "1.5px solid var(--bn-border)",
    color: "var(--bn-ink-45)",
    fontFamily: "var(--bn-font-mono)",
    fontSize: "var(--bn-text-body-sm-size)",
    whiteSpace: "nowrap",
  };
  return (
    <span style={{ display: "flex", alignItems: "stretch", minWidth: 0 }}>
      {prefix ? (
        <span
          style={{
            ...affix,
            borderRight: "none",
            borderRadius: "var(--bn-radius-md) 0 0 var(--bn-radius-md)",
          }}
        >
          {prefix}
        </span>
      ) : null}
      <input
        inputMode="numeric"
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value.replace(/[^\d]/g, ""))}
        style={{
          ...CONTROL,
          fontFamily: "var(--bn-font-mono)",
          minWidth: 0,
          flex: 1,
          borderRadius: prefix
            ? suffix
              ? "0"
              : "0 var(--bn-radius-md) var(--bn-radius-md) 0"
            : suffix
              ? "var(--bn-radius-md) 0 0 var(--bn-radius-md)"
              : "var(--bn-radius-md)",
        }}
      />
      {suffix ? (
        <span
          style={{
            ...affix,
            borderLeft: "none",
            borderRadius: "0 var(--bn-radius-md) var(--bn-radius-md) 0",
          }}
        >
          {suffix}
        </span>
      ) : null}
    </span>
  );
}

export function Select({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      style={{ ...CONTROL, font: "inherit" }}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

/**
 * A toggle that is 52 px of target, not 18 px of checkbox inside 52 px of label.
 *
 * The first version of this was a native `<input type="checkbox">` in a
 * `<label>` carrying the target height, which is the standard accessible
 * pattern and passes every audit: clicking the label toggles the box, so the
 * hit area really is 52 px.
 *
 * `check-invariants.mjs` refused it, and on reflection it was right to. Not
 * because the hit area was wrong — it wasn't — but because CLAUDE.md §10's
 * reason for the floor is not hit-testing in the abstract. It is a stylist
 * standing up, one-handed, with wet hands, and a client on a phone on 3G. An
 * 18 px box that is *technically* 52 px of target still reads as an 18 px box,
 * and is still aimed at like one. The staff screens already answered this: no
 * checkbox appears anywhere in them, only full-height rows.
 *
 * So this is a `button` with `aria-pressed`, which is the correct role for a
 * toggle and gives keyboard and screen-reader behaviour without a native input
 * to fight. The tick box is drawn and `aria-hidden` — the pressed state is
 * already on the button, so the square conveys nothing to a screen reader that
 * the button has not said, and it is not separately reachable by anyone.
 */
export function Toggle({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: ReactNode;
  hint?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={checked}
      onClick={() => onChange(!checked)}
      style={{
        minHeight: TARGET,
        width: "100%",
        display: "flex",
        alignItems: "center",
        gap: "var(--bn-space-5)",
        padding: "var(--bn-space-4) var(--bn-space-5)",
        borderRadius: "var(--bn-radius-md)",
        border: checked ? "1.5px solid var(--bn-accent)" : "1.5px solid var(--bn-border)",
        background: checked ? "var(--bn-clay-50)" : "var(--bn-surface)",
        cursor: "pointer",
        textAlign: "left",
        fontFamily: "var(--bn-font-ui)",
        fontSize: "var(--bn-text-body-size)",
        color: "var(--bn-ink)",
      }}
    >
      <Tick checked={checked} />
      <span style={{ display: "grid", gap: "var(--bn-space-2)", minWidth: 0 }}>
        <span>{label}</span>
        {hint ? (
          <span style={{ color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
            {hint}
          </span>
        ) : null}
      </span>
    </button>
  );
}

/**
 * The drawn box. `aria-hidden` because the state it shows is already on the
 * button's `aria-pressed`, so announcing it twice would be the bug — and
 * because that is what makes it decoration rather than a small target.
 */
export function Tick({ checked }: { checked: boolean }) {
  return (
    <span
      aria-hidden="true"
      style={{
        width: 22,
        height: 22,
        flexShrink: 0,
        display: "grid",
        placeItems: "center",
        borderRadius: "var(--bn-radius-sm)",
        border: checked ? "none" : "1.5px solid var(--bn-border)",
        background: checked ? "var(--bn-accent)" : "var(--bn-surface)",
        color: "#fff",
        fontSize: 14,
        lineHeight: 1,
      }}
    >
      {checked ? "✓" : ""}
    </span>
  );
}

/** The design's empty state: dashed panel, one heading, one sentence, one action. */
export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div
      style={{
        border: "1.5px dashed var(--bn-border)",
        borderRadius: "var(--bn-radius-card)",
        padding: "var(--bn-space-9)",
        display: "grid",
        gap: "var(--bn-space-5)",
        justifyItems: "start",
        background: "var(--bn-canvas)",
      }}
    >
      <p
        style={{
          margin: 0,
          fontFamily: "var(--bn-font-display)",
          fontSize: "var(--bn-text-title-size)",
        }}
      >
        {title}
      </p>
      {children}
    </div>
  );
}

export function ErrorPanel({ children }: { children?: ReactNode }) {
  if (!children) return null;
  return (
    <p
      role="alert"
      style={{
        margin: 0,
        padding: "var(--bn-space-6) var(--bn-space-7)",
        borderRadius: "var(--bn-radius-card)",
        background: "var(--bn-fail-50)",
        color: "var(--bn-fail-700)",
      }}
    >
      {children}
    </p>
  );
}

/** A row of fields that becomes a column on a narrow screen. */
export function Grid({ children, min = 220 }: { children: ReactNode; min?: number }) {
  return (
    <div
      style={{
        display: "grid",
        gap: "var(--bn-space-6)",
        gridTemplateColumns: `repeat(auto-fit, minmax(${min}px, 1fr))`,
      }}
    >
      {children}
    </div>
  );
}

/** Ordinary prose, at the size the rest of the screen uses. */
export function Note({ children }: { children: ReactNode }) {
  return (
    <p
      style={{
        margin: 0,
        color: "var(--bn-ink-70)",
        fontSize: "var(--bn-text-body-sm-size)",
        textWrap: "pretty",
      }}
    >
      {children}
    </p>
  );
}
