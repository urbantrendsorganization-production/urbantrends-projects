"use client";

/**
 * `/m/<token>` — the manage page. Where the SMS lands, and what it can do.
 *
 * Slice 6 shipped `/booking/<id>`, read-only, because a link to a page that
 * could not do what the SMS implied was worse than a link to one that could
 * only show the booking. This is the real thing: cancel and reschedule, with
 * the token as the whole of the session (CLAUDE.md §12).
 *
 * `/booking/<id>` stays as the fallback for a booking with no live token — a
 * walk-in, or a cancellation whose token has just been revoked — so no message
 * ever links to a 404 again.
 *
 * ## The figure, before the confirm
 *
 * The cancel screen shows what *this* cancellation produces and how much, not
 * the general rule. §5 requires the terms to be readable before money moves,
 * and "you will be refunded KES 875" is a term in a way that "cancellations
 * more than 24 hours ahead are refundable" is not. The figure comes from
 * `actions.cancel_outcome` / `cancel_amount_kes`, computed by the same function
 * the cancel endpoint applies, so the screen cannot promise what the API will
 * refuse.
 */

import { INVARIANTS } from "@booknasi/tokens";
import { PUBLIC_API_PREFIX, money, refundSentence } from "@booknasi/booking-core";
import { useCallback, useEffect, useState } from "react";

import { API_BASE } from "../../../lib/api";

type Actions = {
  can_cancel: boolean;
  can_reschedule: boolean;
  moves_left: number;
  cancel_outcome: "refund" | "credit" | "nothing";
  cancel_amount_kes: number;
  credit_days: number;
  refund_window_hours: number;
};

type Booking = {
  id: string;
  status: string;
  starts_at: string;
  local_time: string;
  local_date: string;
  staff_name: string;
  staff_id: string;
  service_name: string;
  service_id: string;
  price_kes: number;
  deposit_kes: number;
  balance_kes: number;
  paid_kes: number;
  shop_name: string;
  shop_slug: string;
  shop_phone: string;
  refund_window_hours: number;
  deposit_credit_days: number;
  actions: Actions;
  credit: { balance_kes: number; expires_at: string; reference: string } | null;
  result?: {
    outcome: string;
    amount_kes: number;
    credit_reference: string;
    credit_expires_at: string | null;
  };
};

type Slot = { starts_at: string; local_time: string; staff_id: string; staff_name: string };

/**
 * The public surface's root, from the one place it is defined.
 *
 * This screen used to build `${API_BASE}${path}` and every request 404'd,
 * because the prefix lived only inside `httpTransport` and the two routes that
 * go through the transport were the only ones that had it. This page is the
 * SMS link — the client's cancel and reschedule — so it was the one screen
 * where the failure mattered most and the one nobody drove by hand. See the
 * note on `PUBLIC_API_PREFIX`, and `core/tests/test_frontend_routes.py`, which
 * is what makes the convention hold rather than the comment.
 */
const PUBLIC_ROOT = `${API_BASE}${PUBLIC_API_PREFIX}`;

async function api(path: string, init?: RequestInit) {
  const reply = await fetch(`${PUBLIC_ROOT}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!reply.ok) throw Object.assign(new Error("request failed"), { status: reply.status });
  return reply.json();
}

export default function ManagePage({ params }: { params: Promise<{ token: string }> }) {
  const [token, setToken] = useState<string | null>(null);
  const [booking, setBooking] = useState<Booking | null>(null);
  const [gone, setGone] = useState(false);
  const [view, setView] = useState<"booking" | "confirmCancel" | "pickSlot" | "done">("booking");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void params.then(({ token: t }) => setToken(t));
  }, [params]);

  const load = useCallback(async (t: string) => {
    try {
      setBooking(await api(`/manage/${t}/`));
    } catch {
      // One shape for every failure, matching the API. See lifecycle_views.
      setGone(true);
    }
  }, []);

  useEffect(() => {
    if (token) void load(token);
  }, [token, load]);

  if (gone) return <Expired />;
  if (!token || !booking) return <Shell>{null}</Shell>;

  // Takes the whole path, not a fragment to be glued on. Assembling a URL from
  // a variable the reader cannot see is exactly how this screen shipped without
  // its `/api/public/v1` prefix for four slices, and it is what stops
  // `core/tests/test_frontend_routes.py` from being able to check it.
  const act = async (path: string, body?: unknown) => {
    setBusy(true);
    setError(null);
    try {
      const next = await api(path, {
        method: "POST",
        body: JSON.stringify(body ?? {}),
      });
      setBooking(next);
      setView("done");
    } catch (err) {
      const status = (err as { status?: number }).status;
      setError(
        status === 409
          ? "That time was just taken. Pick another."
          : "That didn't go through. Try again, or call the shop.",
      );
      if (status === 409) setView("pickSlot");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Shell>
      <Header booking={booking} />
      {error && <Notice tone="fail">{error}</Notice>}

      {view === "booking" && (
        <BookingView booking={booking} onCancel={() => setView("confirmCancel")} onMove={() => setView("pickSlot")} />
      )}
      {view === "confirmCancel" && (
        <ConfirmCancel
          booking={booking}
          busy={busy}
          onBack={() => setView("booking")}
          onConfirm={() => void act(`/manage/${token}/cancel/`)}
        />
      )}
      {view === "pickSlot" && (
        <PickSlot
          booking={booking}
          busy={busy}
          onBack={() => setView("booking")}
          onPick={(slot) =>
            void act(`/manage/${token}/reschedule/`, {
              starts_at: slot.starts_at,
              staff: slot.staff_id,
            })
          }
        />
      )}
      {view === "done" && <Done booking={booking} />}
    </Shell>
  );
}

// ------------------------------------------------------------------- screens

function BookingView({
  booking,
  onCancel,
  onMove,
}: {
  booking: Booking;
  onCancel: () => void;
  onMove: () => void;
}) {
  const a = booking.actions;
  return (
    <>
      <Panel>
        <div className="bn-time" style={{ fontSize: "var(--bn-text-money-size)", fontWeight: 600 }}>
          {booking.local_time}
        </div>
        <p style={{ margin: "var(--bn-space-2) 0 0", color: "var(--bn-ink-45)" }}>
          {booking.service_name} · {booking.staff_name}
        </p>
      </Panel>

      <Panel>
        <Row label="Total" value={money(booking.price_kes)} />
        <Row label="Deposit paid" value={money(booking.paid_kes)} strong />
        <Row label="Balance at the shop" value={money(booking.balance_kes)} />
        <p style={{ margin: "var(--bn-space-6) 0 0", color: "var(--bn-ink-70)", fontSize: "var(--bn-text-body-sm-size)" }}>
          {refundSentence(booking.refund_window_hours, booking.deposit_credit_days)}
        </p>
      </Panel>

      {booking.credit && (
        <Panel>
          <Row label="Credit at this shop" value={money(booking.credit.balance_kes)} strong />
          <p style={{ margin: "var(--bn-space-2) 0 0", color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
            Quote {booking.credit.reference}. It comes off your next booking here automatically.
          </p>
        </Panel>
      )}

      {a.can_reschedule && (
        <Button onClick={onMove}>
          Move this booking{a.moves_left <= 1 ? " (last move online)" : ""}
        </Button>
      )}
      {a.can_cancel && (
        <Button onClick={onCancel} tone="quiet">
          Cancel this booking
        </Button>
      )}
      {!a.can_cancel && !a.can_reschedule && (
        <Notice tone="quiet">
          This booking can&apos;t be changed online. Call {booking.shop_phone || "the shop"}.
        </Notice>
      )}
      {booking.shop_phone && <CallLink phone={booking.shop_phone} />}
    </>
  );
}

function ConfirmCancel({
  booking,
  busy,
  onBack,
  onConfirm,
}: {
  booking: Booking;
  busy: boolean;
  onBack: () => void;
  onConfirm: () => void;
}) {
  const a = booking.actions;
  // The actual figure and the actual outcome, not the general rule. This is the
  // screen §5's "before they pay" requirement is really about — the client is
  // deciding, and the thing they need is what it costs *them*, today.
  const line =
    a.cancel_outcome === "refund"
      ? `Your ${money(a.cancel_amount_kes)} deposit will be refunded by the shop.`
      : a.cancel_outcome === "credit"
        ? `You're inside the ${a.refund_window_hours}-hour window, so your ${money(a.cancel_amount_kes)} deposit becomes credit at ${booking.shop_name} for ${a.credit_days} days — usable on any service.`
        : "Nothing was taken from your M-Pesa, so there's nothing to return.";

  return (
    <>
      <Notice tone={a.cancel_outcome === "credit" ? "warn" : "quiet"}>{line}</Notice>
      {a.can_reschedule && (
        <Notice tone="quiet">
          Moving it instead keeps the full {money(a.cancel_amount_kes)} against a new time.
        </Notice>
      )}
      <Button onClick={onConfirm} disabled={busy}>
        {busy ? "Cancelling…" : "Yes, cancel it"}
      </Button>
      <Button onClick={onBack} tone="quiet">
        Keep my booking
      </Button>
    </>
  );
}

function PickSlot({
  booking,
  busy,
  onBack,
  onPick,
}: {
  booking: Booking;
  busy: boolean;
  onBack: () => void;
  onPick: (slot: Slot) => void;
}) {
  const [date, setDate] = useState(booking.local_date);
  const [slots, setSlots] = useState<Slot[] | null>(null);

  useEffect(() => {
    setSlots(null);
    void fetch(
      `${PUBLIC_ROOT}/shops/${booking.shop_slug}/services/${booking.service_id}/availability/?date=${date}&staff=${booking.staff_id}`,
    )
      .then((r) => r.json())
      .then((body) => setSlots(body.by_staff?.[0]?.slots ?? body.any_staff ?? []))
      .catch(() => setSlots([]));
  }, [date, booking.shop_slug, booking.service_id, booking.staff_id]);

  return (
    <>
      <Notice tone="quiet">
        Same service, same stylist. Your {money(booking.paid_kes)} deposit moves with it.
      </Notice>
      <input
        type="date"
        value={date}
        onChange={(event) => setDate(event.target.value)}
        style={{
          minHeight: INVARIANTS.minTargetHeightPx,
          borderRadius: "var(--bn-radius-md)",
          border: "1.5px solid var(--bn-border)",
          padding: "0 var(--bn-space-6)",
          background: "var(--bn-surface)",
          color: "var(--bn-ink)",
          fontSize: "var(--bn-text-body-lg-size)",
        }}
      />
      {slots === null && <Notice tone="quiet">Loading times…</Notice>}
      {slots?.length === 0 && <Notice tone="quiet">Nothing free that day. Try another.</Notice>}
      {slots && slots.length > 0 && (
        // Invariant 2 (CLAUDE.md §10): three per row, from the constant.
        <div
          style={{
            display: "grid",
            gridTemplateColumns: `repeat(${INVARIANTS.slotsPerRow}, 1fr)`,
            gap: "var(--bn-space-4)",
          }}
        >
          {slots.map((slot) => (
            <button
              key={slot.starts_at}
              onClick={() => onPick(slot)}
              disabled={busy}
              className="bn-time"
              style={{
                minHeight: INVARIANTS.minTargetHeightPx,
                borderRadius: "var(--bn-radius-md)",
                border: "1.5px solid var(--bn-border)",
                background: "var(--bn-surface)",
                color: "var(--bn-ink)",
                fontSize: "var(--bn-text-body-lg-size)",
              }}
            >
              {slot.local_time}
            </button>
          ))}
        </div>
      )}
      <Button onClick={onBack} tone="quiet">
        Keep the time I have
      </Button>
    </>
  );
}

function Done({ booking }: { booking: Booking }) {
  const result = booking.result;
  if (booking.status === "cancelled") {
    return (
      <>
        <Notice tone="quiet">
          Cancelled. {result?.outcome === "credit"
            ? `Your ${money(result.amount_kes)} is credit at ${booking.shop_name} — quote ${result.credit_reference}.`
            : result?.outcome === "refund"
              ? `The shop will refund your ${money(result.amount_kes)}.`
              : "Nothing was taken from your M-Pesa."}
        </Notice>
        <p style={{ margin: 0, color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
          We&apos;ve sent you a confirmation by SMS.
        </p>
        {booking.shop_phone && <CallLink phone={booking.shop_phone} />}
      </>
    );
  }
  return (
    <>
      <Notice tone="quiet">
        Moved. You&apos;re now booked for {booking.local_time} with {booking.staff_name}. Your
        deposit came with it.
      </Notice>
      <p style={{ margin: 0, color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
        We&apos;ve sent you a confirmation by SMS.
      </p>
    </>
  );
}

function Expired() {
  // Not a bare 403. A client whose only link has died needs the next step, and
  // "call the shop" is the next step. See `manage_tokens` on why the API cannot
  // tell them *which* failure this was.
  return (
    <Shell>
      <Notice tone="quiet">
        This link has expired or the booking is no longer active. If you need to change
        something, call the shop.
      </Notice>
    </Shell>
  );
}

// -------------------------------------------------------------------- pieces

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main
      style={{
        maxWidth: 480,
        margin: "0 auto",
        minHeight: "100vh",
        padding: "var(--bn-space-9) var(--bn-space-gutter)",
        background: "var(--bn-canvas)",
        display: "grid",
        gap: "var(--bn-space-7)",
        alignContent: "start",
      }}
    >
      {children}
    </main>
  );
}

function Header({ booking }: { booking: Booking }) {
  return (
    <header style={{ display: "grid", gap: "var(--bn-space-2)" }}>
      <h1 style={{ margin: 0, fontSize: "var(--bn-text-money-size)", fontWeight: 600 }}>
        {booking.shop_name}
      </h1>
      <p style={{ margin: 0, color: "var(--bn-ink-45)" }}>
        {booking.status === "cancelled" ? "This booking was cancelled." : "Your booking"}
      </p>
    </header>
  );
}

function Panel({ children }: { children: React.ReactNode }) {
  return (
    <section
      style={{
        padding: "var(--bn-space-7)",
        borderRadius: "var(--bn-radius-panel)",
        background: "var(--bn-surface)",
        border: "1.5px solid var(--bn-border)",
      }}
    >
      {children}
    </section>
  );
}

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "var(--bn-space-2) 0" }}>
      <span style={{ color: "var(--bn-ink-45)" }}>{label}</span>
      <span className="bn-money" style={{ fontWeight: strong ? 600 : 400 }}>
        {value}
      </span>
    </div>
  );
}

function Button({
  children,
  onClick,
  disabled,
  tone = "loud",
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  tone?: "loud" | "quiet";
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        // Invariant 1 (CLAUDE.md §10). Not themeable, not overridable.
        minHeight: INVARIANTS.minTargetHeightPx,
        borderRadius: "var(--bn-radius-md)",
        border: tone === "loud" ? "none" : "1.5px solid var(--bn-border)",
        background: tone === "loud" ? "var(--bn-accent)" : "transparent",
        color: tone === "loud" ? "#fff" : "var(--bn-ink)",
        fontSize: "var(--bn-text-body-lg-size)",
        opacity: disabled ? 0.6 : 1,
      }}
    >
      {children}
    </button>
  );
}

function CallLink({ phone }: { phone: string }) {
  return (
    <a
      href={`tel:${phone}`}
      style={{
        minHeight: INVARIANTS.minTargetHeightPx,
        display: "grid",
        placeItems: "center",
        borderRadius: "var(--bn-radius-md)",
        border: "1.5px solid var(--bn-border)",
        color: "var(--bn-ink)",
        textDecoration: "none",
        fontSize: "var(--bn-text-body-lg-size)",
      }}
    >
      Call {phone}
    </a>
  );
}

function Notice({ children, tone }: { children: React.ReactNode; tone: "quiet" | "warn" | "fail" }) {
  const background =
    tone === "fail" ? "var(--bn-fail-50)" : tone === "warn" ? "var(--bn-hold-50)" : "var(--bn-surface)";
  const color =
    tone === "fail" ? "var(--bn-fail-700)" : tone === "warn" ? "var(--bn-hold-700)" : "var(--bn-ink-70)";
  return (
    <p
      style={{
        margin: 0,
        padding: "var(--bn-space-7)",
        borderRadius: "var(--bn-radius-panel)",
        background,
        color,
        fontSize: "var(--bn-text-body-size)",
      }}
    >
      {children}
    </p>
  );
}
