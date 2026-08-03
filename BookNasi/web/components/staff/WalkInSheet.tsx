"use client";

/**
 * Three taps. CLAUDE.md §4: "If staff can't record one in three taps, they
 * won't, the calendar drifts from reality, and online bookings start colliding
 * with people already in the chair."
 *
 *   Tap 1  service — this staff member's five most-recorded first
 *   Tap 2  who     — "Me" pre-selected
 *   Tap 3  time    — defaulting to now → now + this person's duration
 *
 * Counted honestly: opening the sheet is the FAB, and taps 1-3 are the three
 * inside it. Tap 2 is pre-selected, so the common case is service → confirm and
 * the third tap is the confirm itself. Nothing is required beyond those three.
 *
 * **The name and phone are asked after saving, never before.** They are not on
 * this screen at all; the row exists first and `AppointmentDetail` attaches a
 * person to it afterwards. A required name field here would be a fourth tap and
 * a keyboard, at a chair, one-handed.
 *
 * **Walk-ins never take a deposit** — the confirm step says so in words rather
 * than hiding the line, because a stylist who has been trained that bookings
 * take a deposit needs to see that this one does not.
 *
 * ## "Something else"
 *
 * Drawn in prose only in the handoff, with no frame around it. It ships as one
 * plain full-width row beneath the five, at the same 64 px height so it is
 * tappable, but with no card, no border and no count — nothing that competes
 * with the five for the first tap. Opening it swaps the list in place rather
 * than pushing a screen, so the back tap is still the sheet's own.
 *
 * ## Collisions
 *
 * Never a validation error above a form. A 409 comes back with ranked options
 * the *engine* computed (`scheduling/collisions.py`), and this renders the
 * first as the primary button. It does no arithmetic of its own — an option is
 * resubmitted exactly as received.
 */

import { useEffect, useState } from "react";

import { ApiError, newRequestId, postWithRetry, api } from "../../lib/api";
import { clock, money, spellDuration } from "../../lib/day";
import { Button, Row, Sheet } from "./primitives";

type ServiceChip = { id: string; name: string; price_kes: number; duration_minutes: number };
type StaffChip = {
  id: string;
  display_name: string;
  is_me: boolean;
  free_now: boolean;
  free_from: string | null;
};
type Option = {
  kind: string;
  label: string;
  staff_id: string;
  staff_name: string;
  starts_at: string;
  duration_minutes: number;
  allow_over_completed: boolean;
};

export function WalkInSheet({
  base,
  onClose,
  onOptimistic,
  onSettled,
  onFailed,
}: {
  base: string;
  onClose: () => void;
  onOptimistic: (draft: any) => void;
  onSettled: (draftId: string, appointment: any) => void;
  onFailed: (draftId: string, reason: string) => void;
}) {
  const [options, setOptions] = useState<{
    top_services: ServiceChip[];
    other_services: ServiceChip[];
    staff: StaffChip[];
    now: string;
  } | null>(null);
  const [showAllServices, setShowAllServices] = useState(false);
  const [service, setService] = useState<ServiceChip | null>(null);
  const [staff, setStaff] = useState<StaffChip | null>(null);
  const [collision, setCollision] = useState<{ detail: string; options: Option[] } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get(`${base}/walk-in/options/`)
      .then((data) => {
        setOptions(data);
        setStaff(data.staff.find((s: StaffChip) => s.is_me) ?? data.staff[0] ?? null);
      })
      .catch(() => setOptions({ top_services: [], other_services: [], staff: [], now: "" }));
  }, [base]);

  function submit(override?: Partial<Option> & { waiting?: boolean }) {
    if (!service || !staff) return;
    setBusy(true);
    const draftId = newRequestId();
    const startsAt = override?.starts_at ?? new Date().toISOString();
    const duration = override?.duration_minutes ?? service.duration_minutes;
    const staffId = override?.staff_id ?? staff.id;
    const staffName = override?.staff_name ?? staff.display_name;

    // The row appears now. A staff action must never block on the network.
    onOptimistic({
      id: draftId,
      status: override?.waiting ? "confirmed" : "in_progress",
      status_label: override?.waiting ? "Waiting" : "In progress",
      source: "walk_in",
      is_waiting: Boolean(override?.waiting),
      starts_at: startsAt,
      ends_at: new Date(new Date(startsAt).getTime() + duration * 60000).toISOString(),
      booked_ends_at: new Date(new Date(startsAt).getTime() + duration * 60000).toISOString(),
      started_at: override?.waiting ? null : startsAt,
      finished_at: null,
      local_time: clock(startsAt),
      staff_id: staffId,
      staff_name: staffName,
      service_name: service.name,
      client_name: "",
      client_phone: "",
      price_kes: service.price_kes,
      deposit_kes: 0,
      duration_minutes: duration,
      undo_to: null,
      pending: "sending",
      // Carried so "Try again" on a failed row can rebuild the same request
      // rather than asking the staff member to redo the three taps.
      serviceId: service.id,
    });
    onClose();

    postWithRetry(`${base}/walk-in/`, {
      service: service.id,
      staff: staffId,
      starts_at: startsAt,
      duration_minutes: duration,
      waiting: Boolean(override?.waiting),
      allow_over_completed: Boolean(override?.allow_over_completed),
      client_request_id: draftId,
    })
      .then((appointment) => onSettled(draftId, appointment))
      .catch((error) => {
        if (error instanceof ApiError && error.status === 409) {
          // Not a failure — a choice. Put the sheet back with the engine's
          // options on it, and take the optimistic row away, because nothing
          // was written.
          onFailed(draftId, "");
          setCollision({ detail: error.body.detail, options: error.body.options ?? [] });
          setBusy(false);
          return;
        }
        onFailed(
          draftId,
          error instanceof ApiError ? error.message : "Couldn't save. Still on this phone only."
        );
      });
  }

  if (collision) {
    return (
      <Sheet title={collision.detail} onClose={() => setCollision(null)}>
        <p style={{ color: "var(--bn-ink-45)", marginTop: 0 }}>
          {collision.options.length
            ? "Pick one and it's recorded straight away."
            : "Nothing fits near this time. Try another stylist or a later slot."}
        </p>
        <div style={{ display: "grid", gap: "var(--bn-space-5)" }}>
          {collision.options.map((option, index) => (
            <Button
              key={`${option.kind}-${option.staff_id}-${option.starts_at}`}
              variant={index === 0 ? "primary" : "secondary"}
              onClick={() => {
                setCollision(null);
                submit(option);
              }}
            >
              {option.label}
            </Button>
          ))}
          <Button variant="quiet" onClick={onClose}>
            Leave it
          </Button>
        </div>
      </Sheet>
    );
  }

  if (!options) {
    return (
      <Sheet title="Walk-in" onClose={onClose}>
        <p style={{ color: "var(--bn-ink-45)" }}>Loading services…</p>
      </Sheet>
    );
  }

  // Tap 1.
  if (!service) {
    const list = showAllServices
      ? [...options.top_services, ...options.other_services]
      : options.top_services;
    return (
      <Sheet title="What are you doing?" onClose={onClose}>
        <div style={{ display: "grid", gap: "var(--bn-space-5)" }}>
          {list.map((chip) => (
            <Row key={chip.id} walkIn onClick={() => setService(chip)}>
              <span style={{ flex: 1 }}>{chip.name}</span>
              <span className="bn-money" style={{ color: "var(--bn-ink-45)" }}>
                {spellDuration(chip.duration_minutes)}
              </span>
            </Row>
          ))}
          {!showAllServices && options.other_services.length > 0 && (
            // Prose only, no frame. See the module docstring.
            <button
              type="button"
              onClick={() => setShowAllServices(true)}
              style={{
                minHeight: 64,
                background: "none",
                border: "none",
                textAlign: "left",
                padding: "0 var(--bn-space-7)",
                color: "var(--bn-ink-45)",
                fontSize: "var(--bn-text-body-lg-size)",
                fontFamily: "var(--bn-font-ui)",
                cursor: "pointer",
              }}
            >
              Something else
            </button>
          )}
        </div>
      </Sheet>
    );
  }

  // Tap 2 — "Me" is already selected, so this is a confirm-or-change screen.
  // Tap 3 is the button at the bottom.
  const ends = new Date(Date.now() + service.duration_minutes * 60000).toISOString();
  return (
    <Sheet title={service.name} onClose={onClose}>
      <div style={{ display: "grid", gap: "var(--bn-space-5)" }}>
        {options.staff.map((person) => (
          <Row
            key={person.id}
            walkIn
            selected={person.id === staff?.id}
            onClick={() => setStaff(person)}
          >
            <span style={{ flex: 1 }}>{person.is_me ? "Me" : person.display_name}</span>
            <span style={{ color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
              {person.free_now
                ? "free"
                : person.free_from
                  ? `free ${clock(person.free_from)}`
                  : "busy"}
            </span>
          </Row>
        ))}
      </div>

      <div
        style={{
          marginTop: "var(--bn-space-9)",
          padding: "var(--bn-space-7)",
          borderRadius: "var(--bn-radius-card)",
          background: "var(--bn-paper)",
          display: "grid",
          gap: "var(--bn-space-3)",
        }}
      >
        <div className="bn-time" style={{ fontSize: "var(--bn-text-money-size)", fontWeight: 600 }}>
          {clock(new Date().toISOString())} → {clock(ends)}
        </div>
        <div className="bn-money" style={{ color: "var(--bn-ink-70)" }}>
          {money(service.price_kes)}
        </div>
        {/* CLAUDE.md §12: walk-ins never take a deposit. Said, not hidden. */}
        <div style={{ color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
          Deposit — not for walk-ins
        </div>
      </div>

      <div style={{ display: "grid", gap: "var(--bn-space-5)", marginTop: "var(--bn-space-9)" }}>
        <Button
          onClick={() => submit()}
          disabled={busy}
          disabledReason="Saving…"
          style={{ minHeight: 56 }}
        >
          Start · {clock(new Date().toISOString())}
        </Button>
        <Button variant="secondary" onClick={() => submit({ waiting: true })} disabled={busy}>
          Waiting, not started
        </Button>
      </div>
    </Sheet>
  );
}
