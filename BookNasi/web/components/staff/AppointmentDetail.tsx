"use client";

/**
 * The appointment detail card.
 *
 * The design's blocks, minus the two CLAUDE.md §12 puts out of v1: **balance
 * collection at the shop** and **cash payment records** are not drawn here at
 * all. The handoff draws `Collect now KES 2,500` and `Mark balance collected`;
 * they are deliberately absent, because building the affordance is what makes
 * it a feature.
 *
 * What is here: the booked span, the money as recorded on the row, the client
 * block with a call button and the name-after-saving form, and the footer
 * actions — including the one-tap, reversible no-show.
 *
 * ## Undo
 *
 * One button, and where it goes is decided by the **server**: `undo_to` comes
 * off the appointment. A client that worked out the inverse itself would be a
 * second copy of `STAFF_TRANSITIONS`, and the two would disagree the first time
 * the table changed. When undo is refused because the chair has gone, the
 * error names what took it — see `Today.tsx`.
 */

import { useState } from "react";

import { api } from "../../lib/api";
import type { Appointment } from "../../lib/day";
import { clock, elapsedSince, money, spellDuration } from "../../lib/day";
import { Button, Sheet } from "./primitives";

const UNDO_LABEL: Record<string, string> = {
  confirmed: "Undo",
  in_progress: "Undo finish",
};

export function AppointmentDetail({
  shop,
  appointment,
  now,
  onClose,
  onTransition,
  onSaved,
}: {
  shop: (path: string) => string;
  appointment: Appointment;
  now: Date;
  onClose: () => void;
  onTransition: (status: string) => void;
  onSaved: (updated: Appointment) => void;
}) {
  const [addingName, setAddingName] = useState(false);
  const [fullName, setFullName] = useState(appointment.client_name);
  const [phone, setPhone] = useState("");
  const [saving, setSaving] = useState(false);

  async function saveClient() {
    setSaving(true);
    try {
      const updated = await api.post(shop(`/appointments/${appointment.id}/client/`), {
        full_name: fullName,
        phone,
      });
      onSaved(updated);
      setAddingName(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Sheet title={appointment.service_name} onClose={onClose}>
      <div style={{ display: "grid", gap: "var(--bn-space-9)" }}>
        <section>
          <div
            className="bn-time"
            style={{ fontSize: "var(--bn-text-money-size)", fontWeight: 600 }}
          >
            {clock(appointment.starts_at)} → {clock(appointment.booked_ends_at)}
          </div>
          <p style={{ color: "var(--bn-ink-45)", margin: "var(--bn-space-2) 0 0" }}>
            {appointment.staff_name} · {spellDuration(appointment.duration_minutes)} ·{" "}
            {appointment.status_label}
            {appointment.status === "in_progress" &&
              appointment.started_at &&
              ` · ${elapsedSince(appointment.started_at, now)} so far`}
            {appointment.finished_at && ` · finished ${clock(appointment.finished_at)}`}
          </p>
        </section>

        <section
          style={{
            background: "var(--bn-paper)",
            borderRadius: "var(--bn-radius-card)",
            padding: "var(--bn-space-7)",
          }}
        >
          <div className="bn-money" style={{ fontWeight: 600 }}>
            {money(appointment.price_kes)}
          </div>
          <p
            style={{
              margin: "var(--bn-space-2) 0 0",
              color: "var(--bn-ink-45)",
              fontSize: "var(--bn-text-body-sm-size)",
            }}
          >
            {appointment.deposit_kes > 0
              ? `${money(appointment.deposit_kes)} deposit on this booking`
              : appointment.source === "walk_in"
                ? "Deposit — not for walk-ins"
                : "No deposit on this booking"}
          </p>
        </section>

        <section>
          <h3
            style={{
              fontSize: "var(--bn-text-label-size)",
              letterSpacing: "var(--bn-text-label-tracking)",
              textTransform: "uppercase",
              color: "var(--bn-ink-45)",
              margin: "0 0 var(--bn-space-5)",
            }}
          >
            Client
          </h3>
          {appointment.client_name || appointment.client_phone ? (
            <div style={{ display: "grid", gap: "var(--bn-space-4)" }}>
              <div style={{ fontSize: "var(--bn-text-body-lg-size)" }}>
                {appointment.client_name || "No name"}
              </div>
              {appointment.client_phone && (
                <a
                  href={`tel:${appointment.client_phone}`}
                  style={{
                    minHeight: 52,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    borderRadius: "var(--bn-radius-md)",
                    border: "1.5px solid var(--bn-border)",
                    color: "var(--bn-ink)",
                    textDecoration: "none",
                    fontWeight: 600,
                  }}
                >
                  Call {appointment.client_phone}
                </a>
              )}
            </div>
          ) : addingName ? (
            <div style={{ display: "grid", gap: "var(--bn-space-5)" }}>
              <Field label="Name" value={fullName} onChange={setFullName} />
              <Field label="Phone" value={phone} onChange={setPhone} inputMode="tel" />
              <Button onClick={saveClient} disabled={saving} disabledReason="Saving…">
                Save
              </Button>
            </div>
          ) : (
            // Asked after saving, never before — the row already exists and
            // already holds the chair.
            <Button variant="secondary" onClick={() => setAddingName(true)}>
              Add name
            </Button>
          )}
        </section>

        <section style={{ display: "grid", gap: "var(--bn-space-5)" }}>
          {appointment.status === "confirmed" && (
            <Button onClick={() => onTransition("in_progress")}>Start now</Button>
          )}
          {appointment.status === "in_progress" && (
            <Button onClick={() => onTransition("completed")} style={{ background: "var(--bn-ink)" }}>
              Finish now
            </Button>
          )}
          {appointment.undo_to && (
            <Button variant="secondary" onClick={() => onTransition(appointment.undo_to!)}>
              {UNDO_LABEL[appointment.undo_to] ?? "Undo"}
            </Button>
          )}
          {(appointment.status === "confirmed" || appointment.status === "in_progress") && (
            <Button variant="destructive" onClick={() => onTransition("no_show")}>
              No-show
            </Button>
          )}
        </section>
      </div>
    </Sheet>
  );
}

function Field({
  label,
  value,
  onChange,
  inputMode,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  inputMode?: "tel";
}) {
  return (
    <label style={{ display: "grid", gap: "var(--bn-space-2)" }}>
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
      <input
        value={value}
        inputMode={inputMode}
        onChange={(event) => onChange(event.target.value)}
        style={{
          minHeight: 52,
          borderRadius: "var(--bn-radius-md)",
          border: "1.5px solid var(--bn-border)",
          padding: "0 var(--bn-space-7)",
          fontSize: "var(--bn-text-body-lg-size)",
          fontFamily: "var(--bn-font-ui)",
          background: "var(--bn-surface)",
          color: "var(--bn-ink)",
        }}
      />
    </label>
  );
}
