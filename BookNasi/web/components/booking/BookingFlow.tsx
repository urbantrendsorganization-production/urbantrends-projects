"use client";

/**
 * Screens 1–4 of the client flow. **A shell, and nothing else.**
 *
 * Every decision here comes from `@booknasi/booking-core`: which step is
 * showing, which slots to draw, whether Continue is allowed and what its label
 * says when it is not. This file renders and calls actions. It contains no
 * `if (step === "slot" && slots.length)` logic that the widget would have to
 * reimplement — that is the whole point of the package existing, and
 * `check-no-framework.mjs` guards the other side of the same boundary.
 *
 * The one thing this file *does* own is layout, because layout is the
 * renderer's job:
 *
 * - **Three slot chips per row** — CLAUDE.md §10, invariant 2, read from
 *   `INVARIANTS.slotsPerRow` and not hardcoded. Denser grids raise mis-taps on
 *   exactly the screen where a mis-tap books the wrong time.
 * - **52 px minimum targets** everywhere, from the same constants.
 * - **Long service names wrap and are never truncated.** `minWidth: 0` on the
 *   flex child and `overflowWrap: anywhere` are what stop a 300-character name
 *   pushing the price off the card; there is a render test for it.
 */

import { INVARIANTS } from "@booknasi/tokens";
import {
  ANYONE,
  type AnyStaffSlot,
  type BookingFlow as Flow,
  type BookingState,
  type Service,
  blockedReason,
  canContinue,
  canResend,
  clock,
  countdownLabel,
  isPaymentStep,
  money,
  offeredSlots,
  refundSentence,
  spellDuration,
  stepNumber,
} from "@booknasi/booking-core";
import { useEffect, useState } from "react";

export function BookingScreens({ flow }: { flow: Flow }) {
  const state = useFlowState(flow);
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    void flow.load();
  }, [flow]);

  // The countdown's timer lives here, not in booking-core: a timer is a
  // resource the host page has opinions about, so the package computes seconds
  // from the server's expiry and the renderer decides how often to ask.
  //
  // Slice 6 adds the poll on the same beat. The client is watching a screen
  // that has to rewrite itself when money they moved in a different app
  // arrives at a server they cannot see, so it asks — every three seconds
  // while a prompt is live, and once more when the timer reaches zero, because
  // the server's grace window means zero is not the end of the story.
  useEffect(() => {
    const watching = state.step === "held" || state.step === "pushed" || state.step === "failed";
    if (!watching) return;
    setSeconds(flow.tick());
    let ticks = 0;
    const beat = setInterval(() => {
      const left = flow.tick();
      setSeconds(left);
      ticks += 1;
      if (left <= 0 || ticks % 3 === 0) void flow.refreshHold();
    }, 1000);
    return () => clearInterval(beat);
  }, [flow, state.step, state.hold?.id]);

  return (
    <main
      style={{
        maxWidth: 480,
        margin: "0 auto",
        minHeight: "100vh",
        paddingBottom: 140,
        background: "var(--bn-canvas)",
      }}
    >
      <Header state={state} onBack={() => flow.back()} />
      {state.error && <ErrorPanel state={state} />}

      {state.step === "service" && <ServiceList state={state} flow={flow} />}
      {state.step === "staff" && <StaffList state={state} flow={flow} />}
      {state.step === "slot" && <SlotPicker state={state} flow={flow} />}
      {state.step === "confirm" && <Confirm state={state} flow={flow} />}
      {state.step === "held" && <Held state={state} flow={flow} seconds={seconds} />}

      {/* Screens 5–8. Which one shows is `stepFor` in booking-core, derived
          from the payment the server put on the hold — never set here. A
          renderer that could choose would be a renderer that can put a client
          on the paid screen when no money moved. */}
      {state.step === "pushed" && <Pushed state={state} flow={flow} seconds={seconds} />}
      {state.step === "paid" && <Paid state={state} />}
      {state.step === "failed" && <Failed state={state} flow={flow} seconds={seconds} />}
      {state.step === "timedOut" && <TimedOut state={state} flow={flow} />}
      {state.step === "slotLost" && <SlotLost state={state} />}
    </main>
  );
}

/** Subscribes to the store. The only React-specific line in the whole flow. */
function useFlowState(flow: Flow): BookingState {
  const [state, setState] = useState(flow.getState());
  useEffect(() => flow.subscribe(setState) as unknown as () => void, [flow]);
  return state;
}

function Header({ state, onBack }: { state: BookingState; onBack: () => void }) {
  const titles: Record<string, string> = {
    service: "What are you booking?",
    staff: "Who with?",
    slot: "When?",
    confirm: "Confirm and pay",
    held: "Your slot is held",
    pushed: "Check your phone",
    paid: "Booked",
    failed: "That payment didn't go through",
    timedOut: "The hold has run out",
    slotLost: "We received your payment",
  };
  return (
    <header style={{ padding: "var(--bn-space-9) var(--bn-space-gutter) var(--bn-space-7)" }}>
      {state.shop && (
        <p style={{ margin: 0, color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
          {state.shop.name}
          {state.shop.area ? ` · ${state.shop.area}` : ""}
        </p>
      )}
      <div style={{ display: "flex", alignItems: "baseline", gap: "var(--bn-space-5)" }}>
        <h1
          style={{
            flex: 1,
            minWidth: 0,
            fontFamily: "var(--bn-font-display)",
            fontSize: "var(--bn-text-title-size)",
            margin: "var(--bn-space-2) 0 0",
          }}
        >
          {titles[state.step]}
        </h1>
        {state.step !== "held" && !isPaymentStep(state.step) && (
          <span className="bn-money" style={{ color: "var(--bn-ink-45)" }}>
            {stepNumber(state)} / 4
          </span>
        )}
      </div>
      {/* No Back on a payment screen. The money either moved or it did not, and
          a back arrow that appears to undo it is the most expensive lie here. */}
      {state.step !== "service" && state.step !== "held" && !isPaymentStep(state.step) && (
        <button
          type="button"
          onClick={onBack}
          style={{
            // The floor applies to Back too. It is the control a client reaches
            // for after a mis-tap, which makes it the last one that should be
            // hard to hit.
            minHeight: INVARIANTS.minTargetHeightPx,
            marginTop: "var(--bn-space-4)",
            background: "none",
            border: "none",
            padding: 0,
            color: "var(--bn-ink-45)",
            fontSize: "var(--bn-text-body-size)",
            cursor: "pointer",
          }}
        >
          ← Back
        </button>
      )}
    </header>
  );
}

function ErrorPanel({ state }: { state: BookingState }) {
  const isLost = state.error?.kind === "slot_taken";
  return (
    <div
      role="alert"
      style={{
        margin: "0 var(--bn-space-gutter) var(--bn-space-7)",
        padding: "var(--bn-space-7)",
        borderRadius: "var(--bn-radius-card)",
        background: isLost ? "var(--bn-fail-50)" : "var(--bn-info-50)",
        color: isLost ? "var(--bn-fail-700)" : "var(--bn-info-700)",
        fontSize: "var(--bn-text-body-size)",
      }}
    >
      {state.error?.message}
    </div>
  );
}

// --------------------------------------------------------------- screen 1

export function ServiceList({ state, flow }: { state: BookingState; flow: Flow }) {
  return (
    <section style={{ padding: "0 var(--bn-space-gutter)", display: "grid", gap: "var(--bn-space-5)" }}>
      {/* The design's reassurance strip. The deposit is priced on every card
          before anything else is asked — the client should never be surprised
          by money at the end. */}
      <p
        style={{
          margin: 0,
          padding: "var(--bn-space-6) var(--bn-space-7)",
          borderRadius: "var(--bn-radius-card)",
          background: "var(--bn-pay-50)",
          color: "var(--bn-pay-700)",
          fontSize: "var(--bn-text-body-sm-size)",
        }}
      >
        A deposit by M-Pesa holds your slot.
        {state.shop ? ` ${refundSentence(state.shop.refund_window_hours)}` : ""}
      </p>
      {state.services.map((service) => (
        <ServiceCard
          key={service.id}
          service={service}
          selected={state.service?.id === service.id}
          onChoose={() => void flow.chooseService(service)}
        />
      ))}
      {!state.services.length && !state.busy && (
        <EmptyPanel>This shop has nothing bookable online yet.</EmptyPanel>
      )}
    </section>
  );
}

/**
 * Exported for the render test. A 300-character service name is not an edge
 * case — "Knotless braids, medium, waist length, with beads and a wash" is an
 * ordinary name and shops write longer. The name wraps and is never truncated
 * client-side (the design's rule); the price keeps its own column.
 */
export function ServiceCard({
  service,
  selected,
  onChoose,
}: {
  service: Service;
  selected: boolean;
  onChoose: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onChoose}
      style={{
        minHeight: INVARIANTS.minTargetHeightPx,
        width: "100%",
        display: "block",
        textAlign: "left",
        padding: "var(--bn-space-7)",
        borderRadius: "var(--bn-radius-card)",
        background: selected ? "var(--bn-clay-50)" : "var(--bn-surface)",
        border: selected ? "2px solid var(--bn-accent)" : "1.5px solid var(--bn-border)",
        cursor: "pointer",
        fontFamily: "var(--bn-font-ui)",
        color: "var(--bn-ink)",
      }}
    >
      <span style={{ display: "flex", gap: "var(--bn-space-5)", alignItems: "baseline" }}>
        <span
          style={{
            // The two properties that stop a very long name collapsing the
            // row: the flex child may shrink below its content, and a single
            // unbroken word breaks rather than pushing the price out.
            flex: 1,
            minWidth: 0,
            overflowWrap: "anywhere",
            fontSize: "var(--bn-text-body-lg-size)",
            lineHeight: 1.35,
          }}
        >
          {service.name}
        </span>
        <span className="bn-money" style={{ flexShrink: 0, fontWeight: 600 }}>
          {money(service.price)}
        </span>
      </span>
      <span
        style={{
          display: "flex",
          gap: "var(--bn-space-5)",
          alignItems: "center",
          marginTop: "var(--bn-space-4)",
          flexWrap: "wrap",
        }}
      >
        <span className="bn-time" style={{ color: "var(--bn-ink-45)" }}>
          {spellDuration(service.duration_minutes)}
        </span>
        <span
          style={{
            padding: "2px var(--bn-space-4)",
            borderRadius: "var(--bn-radius-pill)",
            background: "var(--bn-clay-50)",
            color: "var(--bn-clay-700)",
            fontSize: "var(--bn-text-body-sm-size)",
          }}
        >
          {money(service.deposit_amount)} deposit
        </span>
      </span>
    </button>
  );
}

// --------------------------------------------------------------- screen 2

function StaffList({ state, flow }: { state: BookingState; flow: Flow }) {
  const soonest = state.availability?.any_staff[0];
  return (
    <section style={{ padding: "0 var(--bn-space-gutter)", display: "grid", gap: "var(--bn-space-5)" }}>
      {/* "Anyone available" is first and pre-selected — and it is
          earliest-available-slot, not an assignment algorithm (CLAUDE.md §12). */}
      <Choice
        selected={state.staffChoice === ANYONE}
        title="Anyone available"
        detail={soonest ? `Soonest: ${clock(soonest.starts_at)}` : "Whoever is free first"}
        onChoose={() => flow.chooseStaff(ANYONE)}
      />
      {state.staffOptions.map((person) => (
        <Choice
          key={person.id}
          selected={state.staffChoice === person.id}
          title={person.display_name}
          // Their own duration for this service — CLAUDE.md §3. Two stylists
          // genuinely take different times over the same job.
          detail={spellDuration(person.duration_minutes)}
          onChoose={() => flow.chooseStaff(person.id)}
        />
      ))}
      <p style={{ color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)", margin: 0 }}>
        Times differ by stylist.
      </p>
    </section>
  );
}

function Choice({
  selected,
  title,
  detail,
  onChoose,
}: {
  selected: boolean;
  title: string;
  detail: string;
  onChoose: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onChoose}
      style={{
        minHeight: INVARIANTS.minTargetHeightPx,
        width: "100%",
        display: "flex",
        alignItems: "center",
        gap: "var(--bn-space-5)",
        textAlign: "left",
        padding: "var(--bn-space-6) var(--bn-space-7)",
        borderRadius: "var(--bn-radius-card)",
        background: selected ? "var(--bn-clay-50)" : "var(--bn-surface)",
        border: selected ? "2px solid var(--bn-accent)" : "1.5px solid var(--bn-border)",
        cursor: "pointer",
        fontFamily: "var(--bn-font-ui)",
        fontSize: "var(--bn-text-body-lg-size)",
        color: "var(--bn-ink)",
      }}
    >
      <span style={{ flex: 1, minWidth: 0, overflowWrap: "anywhere" }}>{title}</span>
      <span
        style={{
          flexShrink: 0,
          color: "var(--bn-ink-45)",
          fontSize: "var(--bn-text-body-sm-size)",
        }}
      >
        {detail}
      </span>
    </button>
  );
}

// --------------------------------------------------------------- screen 3

function SlotPicker({ state, flow }: { state: BookingState; flow: Flow }) {
  const slots = offeredSlots(state);
  const today = state.date ?? new Date().toISOString().slice(0, 10);

  useEffect(() => {
    if (!state.date) void flow.chooseDate(today);
  }, [flow, state.date, today]);

  return (
    <section style={{ padding: "0 var(--bn-space-gutter)" }}>
      <DayStrip
        selected={state.date}
        onChoose={(date) => void flow.chooseDate(date)}
        from={today}
      />
      {slots.length ? (
        <SlotGrid slots={slots} chosen={state.slot} onChoose={(slot) => flow.chooseSlot(slot)} />
      ) : (
        !state.busy && (
          <EmptyPanel>
            {/* The design's rule: never a generic apology, always the next real
                option. Without one, say plainly that there is none. */}
            Nothing free that day. Try another date, or pick “Anyone available”.
          </EmptyPanel>
        )
      )}
      <ContinueBar state={state} onContinue={() => {}} label="Pick a time" hidden />
    </section>
  );
}

function DayStrip({
  selected,
  onChoose,
  from,
}: {
  selected: string | null;
  onChoose: (date: string) => void;
  from: string;
}) {
  const days = Array.from({ length: 7 }, (_, offset) => {
    const day = new Date(`${from}T00:00:00Z`);
    day.setUTCDate(day.getUTCDate() + offset);
    return day.toISOString().slice(0, 10);
  });
  return (
    <div
      style={{
        display: "flex",
        gap: "var(--bn-space-4)",
        overflowX: "auto",
        paddingBottom: "var(--bn-space-6)",
      }}
    >
      {days.map((day) => (
        <button
          key={day}
          type="button"
          onClick={() => onChoose(day)}
          style={{
            minHeight: INVARIANTS.minTargetHeightPx,
            minWidth: 60,
            flexShrink: 0,
            borderRadius: "var(--bn-radius-md)",
            border: "1.5px solid var(--bn-border)",
            background: selected === day ? "var(--bn-ink)" : "var(--bn-surface)",
            color: selected === day ? "#fff" : "var(--bn-ink)",
            cursor: "pointer",
            fontFamily: "var(--bn-font-ui)",
          }}
        >
          {new Date(`${day}T00:00:00Z`).toLocaleDateString("en-GB", {
            timeZone: "Africa/Nairobi",
            weekday: "short",
            day: "numeric",
          })}
        </button>
      ))}
    </div>
  );
}

/**
 * Exported for the render test.
 *
 * **Three per row is CLAUDE.md §10, invariant 2** — read from `INVARIANTS`, not
 * written as a 3 here, so a host stylesheet cannot reach it and a redesign
 * cannot quietly densify it. Denser grids raise mis-taps on the one screen
 * where a mis-tap books the wrong time; wider ones push the afternoon below the
 * fold.
 */
export function SlotGrid({
  slots,
  chosen,
  onChoose,
}: {
  slots: AnyStaffSlot[];
  chosen: AnyStaffSlot | null;
  onChoose: (slot: AnyStaffSlot) => void;
}) {
  const morning = slots.filter((slot) => Number(slot.local_time.slice(0, 2)) < 12);
  const afternoon = slots.filter((slot) => Number(slot.local_time.slice(0, 2)) >= 12);
  return (
    <>
      {[
        ["Morning", morning],
        ["Afternoon", afternoon],
      ].map(([label, group]) =>
        (group as AnyStaffSlot[]).length ? (
          <div key={label as string} style={{ marginBottom: "var(--bn-space-9)" }}>
            <h2
              style={{
                fontSize: "var(--bn-text-label-size)",
                letterSpacing: "var(--bn-text-label-tracking)",
                textTransform: "uppercase",
                color: "var(--bn-ink-45)",
                margin: "0 0 var(--bn-space-5)",
              }}
            >
              {label as string}
            </h2>
            <div
              data-testid="slot-grid"
              style={{
                display: "grid",
                gridTemplateColumns: `repeat(${INVARIANTS.slotsPerRow}, minmax(0, 1fr))`,
                gap: "var(--bn-space-4)",
              }}
            >
              {(group as AnyStaffSlot[]).map((slot) => (
                <button
                  key={`${slot.staff_id}-${slot.starts_at}`}
                  type="button"
                  onClick={() => onChoose(slot)}
                  style={{
                    minHeight: INVARIANTS.minTargetHeightPx,
                    borderRadius: "var(--bn-radius-md)",
                    border:
                      chosen?.starts_at === slot.starts_at
                        ? "2px solid var(--bn-accent)"
                        : "1.5px solid var(--bn-border)",
                    background:
                      chosen?.starts_at === slot.starts_at
                        ? "var(--bn-accent)"
                        : "var(--bn-surface)",
                    color: chosen?.starts_at === slot.starts_at ? "#fff" : "var(--bn-ink)",
                    fontFamily: "var(--bn-font-mono)",
                    fontVariantNumeric: "tabular-nums",
                    fontSize: "15.5px",
                    cursor: "pointer",
                  }}
                >
                  {slot.local_time}
                </button>
              ))}
            </div>
          </div>
        ) : null
      )}
    </>
  );
}

// --------------------------------------------------------------- screen 4

function Confirm({ state, flow }: { state: BookingState; flow: Flow }) {
  const service = state.service!;
  const slot = state.slot!;
  return (
    <section style={{ padding: "0 var(--bn-space-gutter)", display: "grid", gap: "var(--bn-space-7)" }}>
      <Card>
        <div className="bn-time" style={{ fontSize: "var(--bn-text-money-size)", fontWeight: 600 }}>
          {clock(slot.starts_at)} → {clock(slot.ends_at)}
        </div>
        <p style={{ margin: "var(--bn-space-2) 0 0", color: "var(--bn-ink-45)" }}>
          {service.name} · {slot.staff_name}
        </p>
      </Card>

      <Card>
        <Line label="Total" value={money(service.price)} />
        <Line label="Deposit now" value={money(service.deposit_amount)} strong />
        <Line label="Balance at the shop" value={money(service.balance_due)} />
        {/* The refund rule sits inside the same card as the money, and is read
            before payment. CLAUDE.md §10: it may be relabelled, never removed. */}
        <p
          style={{
            margin: "var(--bn-space-6) 0 0",
            color: "var(--bn-ink-70)",
            fontSize: "var(--bn-text-body-sm-size)",
          }}
        >
          {refundSentence(
            state.shop?.refund_window_hours ?? 24,
            state.shop?.deposit_credit_days ?? 60,
          )}
        </p>
      </Card>

      <Card>
        <label style={{ display: "grid", gap: "var(--bn-space-3)" }}>
          <span
            style={{
              fontSize: "var(--bn-text-label-size)",
              letterSpacing: "var(--bn-text-label-tracking)",
              textTransform: "uppercase",
              color: "var(--bn-ink-45)",
            }}
          >
            M-Pesa number
          </span>
          <span style={{ display: "flex", alignItems: "stretch" }}>
            <span
              className="bn-money"
              style={{
                minHeight: INVARIANTS.minTargetHeightPx,
                display: "flex",
                alignItems: "center",
                padding: "0 var(--bn-space-6)",
                borderRadius: "var(--bn-radius-md) 0 0 var(--bn-radius-md)",
                border: "1.5px solid var(--bn-border)",
                borderRight: "none",
                color: "var(--bn-ink-45)",
              }}
            >
              +254
            </span>
            <input
              inputMode="tel"
              value={state.phone}
              onChange={(event) => flow.setPhone(event.target.value)}
              placeholder="712 345 678"
              style={{
                flex: 1,
                minWidth: 0,
                minHeight: INVARIANTS.minTargetHeightPx,
                borderRadius: "0 var(--bn-radius-md) var(--bn-radius-md) 0",
                border: "1.5px solid var(--bn-border)",
                padding: "0 var(--bn-space-6)",
                fontFamily: "var(--bn-font-mono)",
                fontSize: "var(--bn-text-body-lg-size)",
                background: "var(--bn-surface)",
                color: "var(--bn-ink)",
              }}
            />
          </span>
        </label>
      </Card>

      <ContinueBar
        state={state}
        onContinue={() => void flow.confirm()}
        label={`Hold my slot · ${money(service.deposit_amount)} ${state.shop ? "deposit" : ""}`.trim()}
      />
    </section>
  );
}

// --------------------------------------------------- the hold, with no payment

/**
 * The hold with no payment against it.
 *
 * Slice 5's whole screen; in slice 6 it is the brief moment between the hold
 * being created and the STK push being accepted, plus the case where the push
 * was refused before it ever went out. The countdown is here and always visible
 * (CLAUDE.md §10, invariant 3), because it is what makes it safe to tell a
 * client to leave the page.
 */
function Held({ state, flow, seconds }: { state: BookingState; flow: Flow; seconds: number }) {
  const hold = state.hold!;
  return (
    <section style={{ padding: "0 var(--bn-space-gutter)", display: "grid", gap: "var(--bn-space-7)" }}>
      <Card>
        <div className="bn-time" style={{ fontSize: "var(--bn-text-money-size)", fontWeight: 600 }}>
          {clock(hold.starts_at)} · {hold.staff_name}
        </div>
        <p style={{ margin: "var(--bn-space-2) 0 0", color: "var(--bn-ink-45)" }}>
          {hold.service_name}
        </p>
      </Card>

      <WaitingPanel state={state} seconds={seconds} />

      <button
        type="button"
        onClick={() => void flow.release()}
        style={{
          minHeight: INVARIANTS.minTargetHeightPx,
          borderRadius: "var(--bn-radius-md)",
          border: "1.5px solid var(--bn-border)",
          background: "var(--bn-surface)",
          color: "var(--bn-ink)",
          fontFamily: "var(--bn-font-ui)",
          fontSize: "var(--bn-text-body-lg-size)",
          fontWeight: 600,
          cursor: "pointer",
        }}
      >
        Give up this slot
      </button>
    </section>
  );
}

// ------------------------------------------------------- screens 5–8, slice 6

/**
 * Screen 5. The prompt is on the phone and we are waiting.
 *
 * Three things on this screen are not decoration:
 *
 * 1. **The countdown**, from `countdownLabel` rather than from the raw number.
 *    Past zero with a push still outstanding it says "Still checking with
 *    M-Pesa", because the server is still holding the slot and a timer that
 *    said "expired" would be lying about the thing it exists to report.
 *    CLAUDE.md §10, invariant 3.
 * 2. **The `*334#` line.** Invariant 4. When the push does not arrive — and it
 *    often does not — this is the difference between a completed deposit and
 *    an abandoned booking. It is never behind a tap.
 * 3. **The shop's phone number, with the truth next to it.** This replaces the
 *    design's "Pay at the shop instead". That control implied the slot was
 *    being held while the client travelled, and it is not, so it is gone and
 *    the sentence that says so is in its place.
 */
export function Pushed({
  state,
  flow,
  seconds,
}: {
  state: BookingState;
  flow: Flow;
  seconds: number;
}) {
  const hold = state.hold!;
  const payment = hold.payment;
  return (
    <section
      style={{ padding: "0 var(--bn-space-gutter)", display: "grid", gap: "var(--bn-space-7)" }}
    >
      <WaitingPanel state={state} seconds={seconds} />

      <Card>
        <p style={{ margin: 0, fontSize: "var(--bn-text-body-lg-size)" }}>
          Enter your M-Pesa PIN to pay{" "}
          <strong className="bn-money">{money(payment?.amount_kes ?? hold.deposit_kes)}</strong>.
        </p>
        <p
          style={{
            margin: "var(--bn-space-5) 0 0",
            color: "var(--bn-ink-70)",
            fontSize: "var(--bn-text-body-size)",
          }}
        >
          {/* Invariant 4. Read from the token, not typed here, so it cannot be
              edited away by a re-skin. */}
          No prompt? Dial <strong className="bn-money">{INVARIANTS.ussdFallback}</strong> and choose
          M-Pesa, then Pay Bill.
        </p>
      </Card>

      <button
        type="button"
        onClick={() => void flow.resend()}
        disabled={!canResend(state, seconds)}
        style={secondaryButton(canResend(state, seconds))}
      >
        {state.busy ? "Sending…" : "Resend the prompt"}
      </button>

      <ShopFallback hold={hold} />
    </section>
  );
}

/** Screen 6. The receipt is first because it is the client's proof at the door. */
export function Paid({ state }: { state: BookingState }) {
  const hold = state.hold!;
  const payment = hold.payment;
  return (
    <section
      style={{ padding: "0 var(--bn-space-gutter)", display: "grid", gap: "var(--bn-space-7)" }}
    >
      <div
        style={{
          padding: "var(--bn-space-9) var(--bn-space-7)",
          borderRadius: "var(--bn-radius-panel)",
          background: "var(--bn-pay-50)",
          color: "var(--bn-pay-700)",
        }}
      >
        {/* The design puts the M-Pesa code above everything else, and it is
            right: it is the one thing the client shows at the door. */}
        <p
          style={{
            margin: 0,
            fontSize: "var(--bn-text-label-size)",
            letterSpacing: "var(--bn-text-label-tracking)",
            textTransform: "uppercase",
          }}
        >
          M-Pesa
        </p>
        <p
          className="bn-money"
          style={{
            margin: "var(--bn-space-2) 0 0",
            fontSize: "var(--bn-text-money-size)",
            fontWeight: 600,
          }}
        >
          {payment?.mpesa_receipt || payment?.support_code}
        </p>
        <p style={{ margin: "var(--bn-space-5) 0 0", fontSize: "var(--bn-text-body-size)" }}>
          {money(payment?.amount_kes ?? hold.deposit_kes)} received.
        </p>
      </div>

      <Card>
        <div className="bn-time" style={{ fontSize: "var(--bn-text-money-size)", fontWeight: 600 }}>
          {clock(hold.starts_at)} · {hold.staff_name}
        </div>
        <p style={{ margin: "var(--bn-space-2) 0 0", color: "var(--bn-ink-45)" }}>
          {hold.service_name}
        </p>
        <div style={{ marginTop: "var(--bn-space-6)" }}>
          <Line label="Balance at the shop" value={money(hold.balance_kes)} />
        </div>
      </Card>

      <p
        style={{
          margin: 0,
          color: "var(--bn-ink-70)",
          fontSize: "var(--bn-text-body-sm-size)",
        }}
      >
        {/* Trimmed to what slice 8 will actually send. The design's footnote
            promised a reminder schedule that does not exist yet, and a
            promise the product cannot keep is worse than no promise. */}
        We've sent you a confirmation by SMS.
      </p>
    </section>
  );
}

/**
 * Screen 7. The payment failed and the hold is still alive.
 *
 * The countdown stays, because the retry has to happen inside it. The design's
 * "book a service with no deposit instead" offer is **not** here: it sends a
 * client hunting through a service list at the worst possible moment, and the
 * thing they wanted is still available for the next minute or two.
 */
export function Failed({
  state,
  flow,
  seconds,
}: {
  state: BookingState;
  flow: Flow;
  seconds: number;
}) {
  const hold = state.hold!;
  return (
    <section
      style={{ padding: "0 var(--bn-space-gutter)", display: "grid", gap: "var(--bn-space-7)" }}
    >
      <div
        style={{
          padding: "var(--bn-space-7)",
          borderRadius: "var(--bn-radius-card)",
          background: "var(--bn-fail-50)",
          color: "var(--bn-fail-700)",
          fontSize: "var(--bn-text-body-lg-size)",
        }}
      >
        {/* The server's copy, not Safaricom's raw ResultDesc. "Merchant does
            not exist" is our problem, not the client's. */}
        {hold.payment?.message}
      </div>

      <WaitingPanel state={state} seconds={seconds} />

      <button
        type="button"
        onClick={() => void flow.resend()}
        disabled={!canResend(state, seconds)}
        style={secondaryButton(canResend(state, seconds), true)}
      >
        {state.busy ? "Sending…" : "Try again"}
      </button>

      <p
        style={{
          margin: 0,
          color: "var(--bn-ink-70)",
          fontSize: "var(--bn-text-body-size)",
        }}
      >
        Or dial <strong className="bn-money">{INVARIANTS.ussdFallback}</strong> and pay by Pay Bill.
      </p>

      <ShopFallback hold={hold} />
    </section>
  );
}

/** The hold ran out and no money moved. The slot is genuinely back in the list. */
function TimedOut({ state, flow }: { state: BookingState; flow: Flow }) {
  const hold = state.hold!;
  return (
    <section
      style={{ padding: "0 var(--bn-space-gutter)", display: "grid", gap: "var(--bn-space-7)" }}
    >
      <Card>
        <p style={{ margin: 0, fontSize: "var(--bn-text-body-lg-size)" }}>
          {hold.local_time} is back in the list and nothing was taken from your M-Pesa.
        </p>
      </Card>
      <button
        type="button"
        onClick={() => void flow.release()}
        style={secondaryButton(true, true)}
      >
        Pick another time
      </button>
      <ShopFallback hold={hold} />
    </section>
  );
}

/**
 * Screen 8. The money arrived and the slot did not survive — `slotLost`.
 *
 * The design said "automatic refund within 24 hr". Nothing automatic exists,
 * the money is with the shop rather than with us, and a promise the product
 * cannot keep is the worst thing to put on the one screen where the client is
 * already unhappy. So this says what actually happens: the shop calls, within
 * the hour, and the support code is what the call is about.
 *
 * Slice 7 replaces the phone call with a "pick another time and carry your
 * deposit" button. The support code stays either way.
 */
export function SlotLost({ state }: { state: BookingState }) {
  const hold = state.hold!;
  const payment = hold.payment;
  return (
    <section
      style={{ padding: "0 var(--bn-space-gutter)", display: "grid", gap: "var(--bn-space-7)" }}
    >
      <div
        style={{
          padding: "var(--bn-space-9) var(--bn-space-7)",
          borderRadius: "var(--bn-radius-panel)",
          background: "var(--bn-fail-50)",
          color: "var(--bn-fail-700)",
        }}
      >
        <p style={{ margin: 0, fontSize: "var(--bn-text-body-lg-size)" }}>
          We received your {money(payment?.amount_kes ?? hold.deposit_kes)}, but {hold.local_time}{" "}
          was taken while the payment was going through.
        </p>
        <p style={{ margin: "var(--bn-space-6) 0 0", fontSize: "var(--bn-text-body-size)" }}>
          Your money is with the shop and they will call you within the hour.
        </p>
      </div>

      <Card>
        <p
          style={{
            margin: 0,
            fontSize: "var(--bn-text-label-size)",
            letterSpacing: "var(--bn-text-label-tracking)",
            textTransform: "uppercase",
            color: "var(--bn-ink-45)",
          }}
        >
          Quote this code
        </p>
        <p
          className="bn-money"
          style={{
            margin: "var(--bn-space-2) 0 0",
            fontSize: "var(--bn-text-money-size)",
            fontWeight: 600,
          }}
        >
          {payment?.support_code}
        </p>
        {payment?.mpesa_receipt && (
          <p
            style={{
              margin: "var(--bn-space-4) 0 0",
              color: "var(--bn-ink-45)",
              fontSize: "var(--bn-text-body-sm-size)",
            }}
          >
            M-Pesa {payment.mpesa_receipt}
          </p>
        )}
      </Card>

      {hold.shop_phone && (
        <a href={`tel:${hold.shop_phone}`} style={{ ...secondaryButton(true, true), display: "grid", placeItems: "center", textDecoration: "none" }}>
          Call {hold.shop_phone}
        </a>
      )}
    </section>
  );
}

/**
 * The countdown, shared by screens 5 and 7. Invariant 3: always visible, never
 * behind a tap, and it renders `countdownLabel` rather than a bare number so
 * that zero-with-a-push-outstanding reads as "still checking" and not as a
 * failure the server has not actually declared.
 */
function WaitingPanel({ state, seconds }: { state: BookingState; seconds: number }) {
  const hold = state.hold!;
  const total = (state.shop?.hold_ttl_minutes ?? 3) * 60;
  const label = countdownLabel(state, seconds);
  const stillChecking = seconds <= 0 && (hold.payment?.push_outstanding ?? false);
  return (
    <div
      style={{
        padding: "var(--bn-space-7)",
        borderRadius: "var(--bn-radius-panel)",
        background: "var(--bn-hold-50)",
        color: "var(--bn-hold-700)",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: "var(--bn-space-5)",
        }}
      >
        <span style={{ fontSize: "var(--bn-text-body-size)" }}>
          {stillChecking ? "Your slot" : "Slot held for"}
        </span>
        <span
          className="bn-time"
          style={{
            fontSize: stillChecking ? "var(--bn-text-body-size)" : "var(--bn-text-money-size)",
            fontWeight: 600,
            textAlign: "right",
          }}
        >
          {label}
        </span>
      </div>
      <div
        aria-hidden
        style={{
          marginTop: "var(--bn-space-5)",
          height: 6,
          borderRadius: 999,
          background: "var(--bn-track)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${Math.max(0, Math.min(100, (seconds / total) * 100))}%`,
            height: "100%",
            background: "var(--bn-hold-600)",
            // Linear. A timer that eases is a timer that lies.
            transition: "width 1s linear",
          }}
        />
      </div>
      <p style={{ margin: "var(--bn-space-6) 0 0", fontSize: "var(--bn-text-body-sm-size)" }}>
        {stillChecking
          ? "M-Pesa is slow sometimes. We're still holding your time while we check."
          : `Nobody else can take ${hold.local_time} until the timer runs out.`}
      </p>
    </div>
  );
}

/**
 * The shop's number, and the sentence that has to sit next to it.
 *
 * This is what replaced "Pay at the shop instead". That button implied the slot
 * was being held while the client made their way over, which it is not — the
 * hold is a few minutes long and the deposit is what keeps it. Offering a
 * WhatsApp link instead would have made the same implication more politely.
 */
function ShopFallback({ hold }: { hold: NonNullable<BookingState["hold"]> }) {
  if (!hold.shop_phone) return null;
  return (
    <p
      style={{
        margin: 0,
        color: "var(--bn-ink-70)",
        fontSize: "var(--bn-text-body-sm-size)",
        lineHeight: 1.5,
      }}
    >
      Stuck? Call the shop on{" "}
      <a href={`tel:${hold.shop_phone}`} className="bn-money" style={{ color: "var(--bn-ink)" }}>
        {hold.shop_phone}
      </a>
      . This time is not being held for you once the timer runs out.
    </p>
  );
}

function secondaryButton(enabled: boolean, prominent = false): React.CSSProperties {
  return {
    minHeight: INVARIANTS.minTargetHeightPx,
    borderRadius: "var(--bn-radius-md)",
    border: prominent ? "none" : "1.5px solid var(--bn-border)",
    background: prominent
      ? enabled
        ? "var(--bn-accent)"
        : "var(--bn-line)"
      : "var(--bn-surface)",
    color: prominent ? (enabled ? "#fff" : "var(--bn-ink-disabled)") : "var(--bn-ink)",
    fontFamily: "var(--bn-font-ui)",
    fontSize: "var(--bn-text-body-lg-size)",
    fontWeight: 600,
    cursor: enabled ? "pointer" : "default",
    opacity: enabled ? 1 : 0.6,
  };
}

// ------------------------------------------------------------------- pieces

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        padding: "var(--bn-space-7)",
        borderRadius: "var(--bn-radius-card)",
        background: "var(--bn-surface)",
        border: "1.5px solid var(--bn-border)",
      }}
    >
      {children}
    </div>
  );
}

function Line({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: "var(--bn-space-5)",
        padding: "var(--bn-space-3) 0",
      }}
    >
      <span style={{ color: strong ? "var(--bn-ink)" : "var(--bn-ink-45)" }}>{label}</span>
      <span className="bn-money" style={{ fontWeight: strong ? 600 : 400, flexShrink: 0 }}>
        {value}
      </span>
    </div>
  );
}

function EmptyPanel({ children }: { children: React.ReactNode }) {
  return (
    <p
      style={{
        padding: "var(--bn-space-11)",
        border: "1.5px dashed var(--bn-border)",
        borderRadius: "var(--bn-radius-panel)",
        color: "var(--bn-ink-45)",
        textAlign: "center",
      }}
    >
      {children}
    </p>
  );
}

function ContinueBar({
  state,
  onContinue,
  label,
  hidden,
}: {
  state: BookingState;
  onContinue: () => void;
  label: string;
  hidden?: boolean;
}) {
  if (hidden) return null;
  const blocked = blockedReason(state);
  return (
    <div
      style={{
        position: "fixed",
        left: 0,
        right: 0,
        bottom: 0,
        padding: "var(--bn-space-6) var(--bn-space-gutter)",
        background: "var(--bn-surface)",
        borderTop: "1px solid var(--bn-line)",
      }}
    >
      <div style={{ maxWidth: 480, margin: "0 auto" }}>
        <button
          type="button"
          onClick={onContinue}
          disabled={!canContinue(state)}
          style={{
            minHeight: 56,
            width: "100%",
            borderRadius: "var(--bn-radius-md)",
            border: "none",
            background: canContinue(state) ? "var(--bn-accent)" : "var(--bn-line)",
            color: canContinue(state) ? "#fff" : "var(--bn-ink-disabled)",
            fontFamily: "var(--bn-font-ui)",
            fontSize: "var(--bn-text-body-lg-size)",
            fontWeight: 600,
            cursor: canContinue(state) ? "pointer" : "default",
          }}
        >
          {/* A disabled button's label says why — the design's rule. */}
          {blocked ?? label}
        </button>
      </div>
    </div>
  );
}
