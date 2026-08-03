"use client";

/**
 * One row on Today.
 *
 * The design's shape: a fixed-width mono time column (so the column never
 * shifts as the digits change), a divider, the service name and client, then
 * the status on the right. Four variants — upcoming, in progress (2 px clay and
 * a clay spine), completed (sunk to paper), no-show (fail tint, struck name).
 *
 * Two states here are not in the design because they belong to the offline
 * scope: `sending` and `failed`. A failed write keeps its row. It does not
 * vanish, it does not go quiet, and it does not pretend to have saved — see
 * `Today.tsx`.
 */

import type { Appointment } from "../../lib/day";
import { clock, elapsedSince, money, spellDuration } from "../../lib/day";
import { Button } from "./primitives";

const TIME_COLUMN = 74;

function tone(appointment: Appointment) {
  if (appointment.pending === "failed")
    return { background: "var(--bn-fail-50)", border: "1.5px solid var(--bn-fail-300)" };
  if (appointment.pending === "sending")
    return { background: "var(--bn-info-50)", border: "1.5px solid var(--bn-border)" };
  if (appointment.status === "in_progress")
    return { background: "var(--bn-surface)", border: "2px solid var(--bn-accent)" };
  if (appointment.status === "no_show")
    return { background: "var(--bn-fail-50)", border: "1.5px solid var(--bn-fail-300)" };
  if (appointment.status === "completed")
    return { background: "var(--bn-paper)", border: "1.5px solid var(--bn-line)" };
  return { background: "var(--bn-surface)", border: "1.5px solid var(--bn-border)" };
}

export function AppointmentRow({
  appointment,
  now,
  onOpen,
  onFinish,
  onRetry,
  onDiscard,
}: {
  appointment: Appointment;
  now: Date;
  onOpen: () => void;
  onFinish: () => void;
  onRetry: () => void;
  onDiscard: () => void;
}) {
  const muted = appointment.status === "completed" || appointment.status === "no_show";
  return (
    <div
      style={{
        borderRadius: "var(--bn-radius-card)",
        overflow: "hidden",
        ...tone(appointment),
      }}
    >
      <button
        type="button"
        onClick={appointment.pending ? undefined : onOpen}
        style={{
          minHeight: 64,
          width: "100%",
          display: "flex",
          gap: "var(--bn-space-6)",
          alignItems: "center",
          padding: "var(--bn-space-6) var(--bn-space-7)",
          background: "none",
          border: "none",
          textAlign: "left",
          cursor: appointment.pending ? "default" : "pointer",
          opacity: muted ? 0.72 : 1,
        }}
      >
        {appointment.status === "in_progress" && (
          <span
            aria-hidden
            style={{
              width: 3,
              alignSelf: "stretch",
              background: "var(--bn-accent)",
              borderRadius: 999,
            }}
          />
        )}
        <span
          className="bn-time"
          style={{ width: TIME_COLUMN, flexShrink: 0, fontWeight: 600, color: "var(--bn-ink)" }}
        >
          {clock(appointment.starts_at)}
        </span>
        <span style={{ flex: 1, minWidth: 0 }}>
          <span
            style={{
              display: "block",
              fontSize: "var(--bn-text-body-lg-size)",
              textDecoration: appointment.status === "no_show" ? "line-through" : "none",
            }}
          >
            {appointment.service_name}
          </span>
          <span
            style={{ display: "block", color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}
          >
            {appointment.client_name || (appointment.source === "walk_in" ? "Walk-in" : "No name yet")}
            {" · "}
            {spellDuration(appointment.duration_minutes)}
            {appointment.deposit_kes > 0 && ` · ${money(appointment.deposit_kes)} deposit`}
          </span>
        </span>
        <span
          style={{
            fontSize: "var(--bn-text-body-sm-size)",
            color:
              appointment.pending === "failed"
                ? "var(--bn-fail-700)"
                : appointment.status === "in_progress"
                  ? "var(--bn-accent)"
                  : "var(--bn-ink-45)",
            textAlign: "right",
            flexShrink: 0,
          }}
        >
          {appointment.pending === "sending"
            ? "Saving…"
            : appointment.pending === "failed"
              ? "Not saved"
              : appointment.status === "in_progress" && appointment.started_at
                ? elapsedSince(appointment.started_at, now)
                : appointment.status_label}
        </span>
      </button>

      {/* The design puts Finish directly beneath the in-progress row, not
          behind a tap into the detail card. It is the commonest action of the
          day and it should not cost a screen. */}
      {appointment.status === "in_progress" && !appointment.pending && (
        <div style={{ padding: "0 var(--bn-space-7) var(--bn-space-6)" }}>
          <Button onClick={onFinish} style={{ background: "var(--bn-ink)" }}>
            Finish now
          </Button>
        </div>
      )}

      {/* A failed write states what happened and offers the way out. It never
          disappears on its own — the staff member decides. */}
      {appointment.pending === "failed" && (
        <div
          style={{
            padding: "0 var(--bn-space-7) var(--bn-space-6)",
            display: "grid",
            gap: "var(--bn-space-4)",
          }}
        >
          <p
            style={{
              margin: 0,
              color: "var(--bn-fail-700)",
              fontSize: "var(--bn-text-body-sm-size)",
            }}
          >
            {appointment.pendingDetail ||
              "This is on this phone only. It is not in the shop's book yet."}
          </p>
          <Button onClick={onRetry} variant="secondary">
            Try again
          </Button>
          <Button onClick={onDiscard} variant="quiet">
            Discard it
          </Button>
        </div>
      )}
    </div>
  );
}
