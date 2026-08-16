"use client";

/**
 * The controls the three auth screens share.
 *
 * Small, and deliberately not a form library. Three forms with four fields
 * between them do not need one, and the thing that actually matters here is
 * already decided elsewhere: CLAUDE.md §10's 52 px floor, and the design's
 * phone input with a fixed `+254` prefix in mono divided by a hairline.
 *
 * ## Why the phone prefix is fixed rather than typed
 *
 * Every account in this product is a Kenyan mobile number — `accounts/phone.py`
 * normalises to `+254` and `USERNAME_FIELD` is the phone, because staff invites
 * arrive by SMS and salon staff often have no working email (CLAUDE.md §12).
 * A free-text field invites `0712…`, `254712…`, `+254 712…` and a space in the
 * middle, and then the person cannot sign in and does not know why. The prefix
 * is drawn, not typed, and the nine digits are all that is asked for.
 *
 * The server still normalises whatever arrives. This is about the client not
 * having to guess, not about trusting the client.
 */

import { INVARIANTS } from "@booknasi/tokens";
import type { ReactNode } from "react";

const TARGET = `${INVARIANTS.minTargetHeightPx}px`;

export function AuthShell({
  title,
  intro,
  children,
  footer,
}: {
  title: string;
  intro?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <main
      style={{
        maxWidth: 420,
        margin: "0 auto",
        minHeight: "100vh",
        padding: "var(--bn-space-11) var(--bn-space-gutter)",
        background: "var(--bn-canvas)",
        display: "grid",
        alignContent: "start",
        gap: "var(--bn-space-9)",
      }}
    >
      <header style={{ display: "grid", gap: "var(--bn-space-4)" }}>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--bn-font-display)",
            fontWeight: 700,
            fontSize: "var(--bn-text-body-lg-size)",
            color: "var(--bn-accent)",
          }}
        >
          BookNasi
        </p>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--bn-font-display)",
            fontSize: "var(--bn-text-display-size)",
            lineHeight: "var(--bn-text-display-leading)",
            letterSpacing: "var(--bn-text-display-tracking)",
          }}
        >
          {title}
        </h1>
        {intro ? (
          <p style={{ margin: 0, color: "var(--bn-ink-70)", textWrap: "pretty" }}>{intro}</p>
        ) : null}
      </header>
      {children}
      {footer ? (
        <p style={{ margin: 0, color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
          {footer}
        </p>
      ) : null}
    </main>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label style={{ display: "grid", gap: "var(--bn-space-3)" }}>
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
      {hint ? (
        <span style={{ color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
          {hint}
        </span>
      ) : null}
    </label>
  );
}

const INPUT: React.CSSProperties = {
  minHeight: TARGET,
  width: "100%",
  padding: "0 var(--bn-space-6)",
  borderRadius: "var(--bn-radius-md)",
  border: "1.5px solid var(--bn-border)",
  background: "var(--bn-surface)",
  color: "var(--bn-ink)",
  fontFamily: "var(--bn-font-ui)",
  fontSize: "var(--bn-text-body-lg-size)",
};

export function TextInput({
  value,
  onChange,
  placeholder,
  autoComplete,
  type = "text",
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  autoComplete?: string;
  type?: "text" | "password";
}) {
  return (
    <input
      type={type}
      value={value}
      autoComplete={autoComplete}
      placeholder={placeholder}
      onChange={(event) => onChange(event.target.value)}
      style={INPUT}
    />
  );
}

/**
 * `+254` drawn, nine digits typed. The design's input spec, and the reason is
 * in this file's header.
 */
export function PhoneInput({
  value,
  onChange,
  autoComplete = "tel",
}: {
  value: string;
  onChange: (value: string) => void;
  autoComplete?: string;
}) {
  return (
    <span style={{ display: "flex", alignItems: "stretch" }}>
      <span
        style={{
          minHeight: TARGET,
          display: "flex",
          alignItems: "center",
          padding: "0 var(--bn-space-6)",
          borderRadius: "var(--bn-radius-md) 0 0 var(--bn-radius-md)",
          border: "1.5px solid var(--bn-border)",
          borderRight: "none",
          color: "var(--bn-ink-45)",
          fontFamily: "var(--bn-font-mono)",
        }}
      >
        +254
      </span>
      <input
        inputMode="tel"
        autoComplete={autoComplete}
        value={value}
        placeholder="712 345 678"
        // Digits only, and never more than nine. A pasted `0712345678` or
        // `+254712345678` loses its prefix here rather than being refused by
        // the server after the person has already pressed the button.
        onChange={(event) => onChange(normaliseLocal(event.target.value))}
        style={{
          ...INPUT,
          borderRadius: "0 var(--bn-radius-md) var(--bn-radius-md) 0",
          fontFamily: "var(--bn-font-mono)",
          minWidth: 0,
          flex: 1,
        }}
      />
    </span>
  );
}

/** The nine digits after `+254`, from whatever the person typed or pasted. */
export function normaliseLocal(raw: string): string {
  let digits = raw.replace(/\D/g, "");
  if (digits.startsWith("254")) digits = digits.slice(3);
  if (digits.startsWith("0")) digits = digits.slice(1);
  return digits.slice(0, 9);
}

/** What the API is sent. `accounts/phone.py` normalises again on arrival. */
export function toE164(local: string): string {
  return `+254${local}`;
}

export function ErrorPanel({ children }: { children: ReactNode }) {
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
        fontSize: "var(--bn-text-body-size)",
      }}
    >
      {children}
    </p>
  );
}
