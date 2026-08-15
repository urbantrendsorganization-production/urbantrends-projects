"use client";

/**
 * `/booking/<id>` — where the confirmation SMS lands.
 *
 * `notifications/service.booking_link` has always pointed here and the route
 * did not exist, so every confirmation SMS linked to a 404. That is a trust bug
 * of the same kind as reminding somebody about a cancelled appointment: the one
 * message the client keeps, pointing at nothing.
 *
 * Thin, and deliberately read-only. This is **not** the signed, expiring manage
 * link with a reschedule and a cancel on it — that is the lifecycle slice, and
 * `booking_link`'s own docstring says widening it is one function when the
 * screen exists. What ships here is what the SMS implies it will find: their
 * booking, and the terms their deposit sits under.
 *
 * The id is the session (CLAUDE.md §12). No login, no token: an unguessable
 * UUID, and a serializer that returns only what its holder already sent.
 */

import { INVARIANTS } from "@booknasi/tokens";
import { type Hold, httpTransport, money, refundSentence } from "@booknasi/booking-core";
import { useEffect, useState } from "react";

import { API_BASE } from "../../../lib/api";

const transport = httpTransport({
  baseUrl: API_BASE,
  fetchImpl: (url: string, init?: RequestInit) => fetch(url, init),
  csrfToken: () => document.cookie.match(/(^| )csrftoken=([^;]+)/)?.[2] ?? "",
});

export default function BookingDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const [hold, setHold] = useState<Hold | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let live = true;
    void params
      .then(({ id }) => transport.getHold(id))
      .then((found) => live && setHold(found))
      .catch(() => live && setMissing(true));
    return () => {
      live = false;
    };
  }, [params]);

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
      {missing && (
        <p style={{ margin: 0, color: "var(--bn-ink-70)" }}>
          We couldn&apos;t find that booking. If you have just paid, call the shop and quote your
          support code.
        </p>
      )}

      {hold && <BookingSummary hold={hold} />}
    </main>
  );
}

function BookingSummary({ hold }: { hold: Hold }) {
  const cancelled = hold.status === "cancelled";
  return (
    <>
      <header style={{ display: "grid", gap: "var(--bn-space-2)" }}>
        <h1 style={{ margin: 0, fontSize: "var(--bn-text-money-size)", fontWeight: 600 }}>
          {hold.shop_name}
        </h1>
        <p style={{ margin: 0, color: "var(--bn-ink-45)" }}>
          {cancelled ? "This booking was cancelled." : "Your booking is confirmed."}
        </p>
      </header>

      <Panel>
        <div className="bn-time" style={{ fontSize: "var(--bn-text-money-size)", fontWeight: 600 }}>
          {hold.local_time}
        </div>
        <p style={{ margin: "var(--bn-space-2) 0 0", color: "var(--bn-ink-45)" }}>
          {hold.service_name} · {hold.staff_name}
        </p>
      </Panel>

      <Panel>
        <Row label="Total" value={money(hold.price_kes)} />
        <Row label="Deposit paid" value={money(hold.deposit_kes)} strong />
        <Row label="Balance at the shop" value={money(hold.balance_kes)} />
        {hold.payment?.mpesa_receipt && (
          <p
            style={{
              margin: "var(--bn-space-4) 0 0",
              color: "var(--bn-ink-45)",
              fontSize: "var(--bn-text-body-sm-size)",
            }}
          >
            M-Pesa {hold.payment.mpesa_receipt}
          </p>
        )}
        {/* The same sentence as the confirm screen, from the same function.
            CLAUDE.md §5: the client reads the terms before they pay, and §12
            settled what they say. Repeating them here is not decoration — this
            is the page they land on when they are deciding whether to cancel,
            which is the moment the credit rule actually matters. */}
        <p
          style={{
            margin: "var(--bn-space-6) 0 0",
            color: "var(--bn-ink-70)",
            fontSize: "var(--bn-text-body-sm-size)",
          }}
        >
          {refundSentence(hold.refund_window_hours, hold.deposit_credit_days)}
        </p>
      </Panel>

      {hold.shop_phone && (
        <a
          href={`tel:${hold.shop_phone}`}
          style={{
            // Invariant 1 (§10). A phone on 3G, one-handed, and the only action
            // on the page — it does not get to be smaller than the floor.
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
          Call {hold.shop_phone}
        </a>
      )}
    </>
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
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: "var(--bn-space-5)",
        padding: "var(--bn-space-2) 0",
      }}
    >
      <span style={{ color: "var(--bn-ink-45)" }}>{label}</span>
      <span className="bn-money" style={{ fontWeight: strong ? 600 : 400 }}>
        {value}
      </span>
    </div>
  );
}
