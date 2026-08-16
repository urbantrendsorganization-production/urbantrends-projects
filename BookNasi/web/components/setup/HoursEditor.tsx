"use client";

/**
 * Opening hours, and dated closures.
 *
 * Seven rows with a toggle each, which is the design's "per-day toggles". The
 * shape matters: `OpeningHours` is one row per weekday and *absence means
 * shut*, so the toggle is not a field on a row — it is whether the row exists.
 * Turning Sunday off deletes it; turning it on creates one. Modelling that as
 * an `is_open` column would have been a second way to be closed, and the
 * availability engine only reads one of them
 * (`scheduling/loading.gather_shop_day` takes the first row for the weekday
 * or, finding none, treats the shop as shut).
 *
 * ## Times are EAT wall-clock and are stored that way
 *
 * `opens_at` is a `TimeField`, not an instant. CLAUDE.md §4: store UTC, render
 * EAT — but a shop's opening time is not an instant, it is "nine o'clock",
 * and it stays nine o'clock. The conversion happens once, in
 * `scheduling/loading`, when a weekday pattern meets a date.
 *
 * ## Saving is per row, not a form submit
 *
 * Each day writes when it changes. Seven days behind one Save button means an
 * owner who edits Tuesday, gets distracted, and loses it — and a partial
 * failure across seven rows has no good story. One row, one request, one
 * visible state.
 */

import { useState } from "react";

import { ApiError, api } from "../../lib/api";
import { firstError } from "../../lib/auth";
import { Button, Empty, ErrorPanel, Field, Note, Section, TextInput, Toggle } from "./primitives";

export type Hours = { id: string; weekday: number; opens_at: string; closes_at: string };
export type Closure = { id: string; starts_on: string; ends_on: string; reason: string };

/** Monday first, matching `Weekday` in `shops/models.py` and Python's own
 *  `date.weekday()`, which `gather_shop_day` indexes by. */
const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

const DEFAULT_OPEN = "08:00";
const DEFAULT_CLOSE = "20:00";

/** `08:00:00` from the API, `08:00` in the input. */
function hhmm(value: string): string {
  return value.slice(0, 5);
}

export function HoursEditor({
  orgId,
  shopId,
  hours,
  closures,
  onChanged,
}: {
  orgId: string;
  shopId: string;
  hours: Hours[];
  closures: Closure[];
  onChanged: () => void;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<number | null>(null);

  const byDay = new Map(hours.map((row) => [row.weekday, row]));

  function run(weekday: number, work: Promise<unknown>) {
    setBusy(weekday);
    setError("");
    work
      .then(() => onChanged())
      .catch((caught) =>
        setError(caught instanceof ApiError ? firstError(caught.body, "Could not save.") : "Could not save.")
      )
      .finally(() => setBusy(null));
  }

  function toggle(weekday: number) {
    const existing = byDay.get(weekday);
    if (existing) {
      run(weekday, api.del(`/api/v1/orgs/${orgId}/shops/${shopId}/opening-hours/${existing.id}/`));
      return;
    }
    // A new day copies the most common existing hours rather than starting at
    // midnight. An owner adding Sunday almost always means "same as Saturday",
    // and 00:00–00:00 is both wrong and refused by the model's check
    // constraint.
    const template = hours[0];
    run(
      weekday,
      api.post(`/api/v1/orgs/${orgId}/shops/${shopId}/opening-hours/`, {
        weekday,
        opens_at: template ? hhmm(template.opens_at) : DEFAULT_OPEN,
        closes_at: template ? hhmm(template.closes_at) : DEFAULT_CLOSE,
      })
    );
  }

  function setTime(row: Hours, field: "opens_at" | "closes_at", value: string) {
    run(
      row.weekday,
      api.patch(`/api/v1/orgs/${orgId}/shops/${shopId}/opening-hours/${row.id}/`, {
        [field]: value,
      })
    );
  }

  return (
    <>
      <Section
        id="setup-hours"
        title="Opening hours"
        intro="Clients are offered times inside these hours and no others. A day that is off is shut."
      >
        <ErrorPanel>{error}</ErrorPanel>
        <div style={{ display: "grid", gap: "var(--bn-space-5)" }}>
          {DAYS.map((label, weekday) => {
            const row = byDay.get(weekday);
            return (
              <div
                key={label}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "var(--bn-space-6)",
                  flexWrap: "wrap",
                  padding: "var(--bn-space-4) var(--bn-space-5)",
                  borderRadius: "var(--bn-radius-md)",
                  border: "1px solid var(--bn-line)",
                  background: row ? "var(--bn-surface)" : "var(--bn-canvas)",
                  opacity: busy === weekday ? 0.6 : 1,
                }}
              >
                <span style={{ minWidth: 170 }}>
                  <Toggle
                    checked={Boolean(row)}
                    onChange={() => toggle(weekday)}
                    label={label}
                  />
                </span>

                {row ? (
                  <div style={{ display: "flex", alignItems: "center", gap: "var(--bn-space-5)" }}>
                    <TextInput
                      type="time"
                      mono
                      value={hhmm(row.opens_at)}
                      onChange={(value) => setTime(row, "opens_at", value)}
                    />
                    <span aria-hidden="true" style={{ color: "var(--bn-ink-45)" }}>
                      to
                    </span>
                    <TextInput
                      type="time"
                      mono
                      value={hhmm(row.closes_at)}
                      onChange={(value) => setTime(row, "closes_at", value)}
                    />
                  </div>
                ) : (
                  <span style={{ color: "var(--bn-ink-45)" }}>Closed</span>
                )}
              </div>
            );
          })}
        </div>
        <Note>Times are EAT. Changes apply to bookings made from now on, not to ones already taken.</Note>
      </Section>

      <ClosuresEditor
        orgId={orgId}
        shopId={shopId}
        closures={closures}
        onChanged={onChanged}
      />
    </>
  );
}

/**
 * Dated closures — a public holiday, a week shut for a refit.
 *
 * A closure beats the weekly pattern outright (`gather_shop_day` checks it
 * first and short-circuits), which is why it is a separate list rather than an
 * exception woven into the seven rows above.
 */
function ClosuresEditor({
  orgId,
  shopId,
  closures,
  onChanged,
}: {
  orgId: string;
  shopId: string;
  closures: Closure[];
  onChanged: () => void;
}) {
  const [starts, setStarts] = useState("");
  const [ends, setEnds] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  function add() {
    setSaving(true);
    setError("");
    api
      .post(`/api/v1/orgs/${orgId}/shops/${shopId}/closures/`, {
        starts_on: starts,
        // A one-day closure is the common case, and `ends_on` is inclusive on
        // the model — so leaving the end blank means the same day, not
        // forever.
        ends_on: ends || starts,
        reason,
      })
      .then(() => {
        setStarts("");
        setEnds("");
        setReason("");
        onChanged();
      })
      .catch((caught) =>
        setError(caught instanceof ApiError ? firstError(caught.body, "Could not save.") : "Could not save.")
      )
      .finally(() => setSaving(false));
  }

  function remove(id: string) {
    api
      .del(`/api/v1/orgs/${orgId}/shops/${shopId}/closures/${id}/`)
      .then(() => onChanged())
      .catch(() => setError("Could not remove that."));
  }

  return (
    <Section
      title="Days you are shut"
      intro="Public holidays, a refit, a family week. These beat your opening hours."
    >
      <ErrorPanel>{error}</ErrorPanel>

      {closures.length ? (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: "var(--bn-space-4)" }}>
          {closures.map((closure) => (
            <li
              key={closure.id}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: "var(--bn-space-6)",
                padding: "var(--bn-space-4) var(--bn-space-6)",
                border: "1px solid var(--bn-line)",
                borderRadius: "var(--bn-radius-md)",
                flexWrap: "wrap",
              }}
            >
              <span style={{ display: "grid", gap: "var(--bn-space-2)" }}>
                <span style={{ fontFamily: "var(--bn-font-mono)" }}>
                  {closure.starts_on === closure.ends_on
                    ? closure.starts_on
                    : `${closure.starts_on} → ${closure.ends_on}`}
                </span>
                {closure.reason ? (
                  <span style={{ color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
                    {closure.reason}
                  </span>
                ) : null}
              </span>
              <Button
                variant="quiet"
                onClick={() => remove(closure.id)}
                style={{ width: "auto", padding: "0 var(--bn-space-6)" }}
              >
                Remove
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <Empty title="Nothing in the diary">
          <Note>Add a date and the booking page will stop offering it.</Note>
        </Empty>
      )}

      <div
        style={{
          display: "grid",
          gap: "var(--bn-space-6)",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          alignItems: "end",
        }}
      >
        <Field label="From">
          <input
            type="date"
            value={starts}
            onChange={(event) => setStarts(event.target.value)}
            style={{
              minHeight: "var(--bn-target-control)",
              width: "100%",
              padding: "0 var(--bn-space-6)",
              borderRadius: "var(--bn-radius-md)",
              border: "1.5px solid var(--bn-border)",
              background: "var(--bn-surface)",
              color: "var(--bn-ink)",
              fontFamily: "var(--bn-font-mono)",
            }}
          />
        </Field>
        <Field label="To" hint="Leave blank for one day.">
          <input
            type="date"
            value={ends}
            min={starts || undefined}
            onChange={(event) => setEnds(event.target.value)}
            style={{
              minHeight: "var(--bn-target-control)",
              width: "100%",
              padding: "0 var(--bn-space-6)",
              borderRadius: "var(--bn-radius-md)",
              border: "1.5px solid var(--bn-border)",
              background: "var(--bn-surface)",
              color: "var(--bn-ink)",
              fontFamily: "var(--bn-font-mono)",
            }}
          />
        </Field>
        <Field label="Reason" hint="Optional. Not shown to clients.">
          <TextInput value={reason} onChange={setReason} placeholder="Madaraka Day" />
        </Field>
        <Button
          onClick={add}
          disabled={!starts || saving}
          disabledReason={!starts ? "Pick a date" : undefined}
          style={{ width: "auto" }}
        >
          {saving ? "Adding…" : "Add"}
        </Button>
      </div>
    </Section>
  );
}
