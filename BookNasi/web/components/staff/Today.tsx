"use client";

/**
 * Today. The adoption screen — CLAUDE.md §7.
 *
 * Not a calendar. Three bands (Now / Next / earlier work in grey), three stat
 * tiles, and a 64 px clay FAB pinned bottom-right that never scrolls away. No
 * tab bar, no hamburger, no week view.
 *
 * ## Offline, exactly as scoped
 *
 * CLAUDE.md §12 puts the full local write queue out of this slice. What ships:
 *
 * - **Optimistic render.** A walk-in row appears the instant it is tapped, with
 *   a pending state. A staff action never blocks on the network.
 * - **Retry.** Network failures and 5xx are retried with backoff by
 *   `postWithRetry`, carrying the same `client_request_id` each time so a retry
 *   of a write the server already took returns that row instead of colliding
 *   with it.
 * - **A stale-read banner.** "Today's list is from 9:12 am." shown whenever the
 *   last successful refresh is more than a minute old.
 *
 * What does not ship, and is therefore stated on screen rather than implied: a
 * failed write lives in this tab's memory only. Close the tab and it is gone.
 * So the failed row says "This is on this phone only. It is not in the shop's
 * book yet." — the one sentence that keeps a staff member from walking away
 * believing it saved.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, api, postWithRetry, shopScope } from "../../lib/api";
import type { Appointment } from "../../lib/day";
import { clock, groupByBand, money } from "../../lib/day";
import { AppointmentDetail } from "./AppointmentDetail";
import { AppointmentRow } from "./AppointmentRow";
import { Button, Toast } from "./primitives";
import { WalkInSheet } from "./WalkInSheet";

const REFRESH_MS = 45_000;
const STALE_AFTER_MS = 60_000;

type DayResponse = {
  date: string;
  server_time: string;
  shop: { id: string; name: string };
  me: { id: string; display_name: string } | null;
  can_view_shop: boolean;
  scope: string;
  totals: { appointments: number; walk_ins: number; deposit_total_kes: number };
  appointments: Appointment[];
};

export function Today({ orgId, shopId }: { orgId: string; shopId: string }) {
  const shop = useMemo(() => shopScope(orgId, shopId), [orgId, shopId]);
  const [day, setDay] = useState<DayResponse | null>(null);
  const [drafts, setDrafts] = useState<Appointment[]>([]);
  const [fetchedAt, setFetchedAt] = useState<Date | null>(null);
  const [now, setNow] = useState(() => new Date());
  const [sheetOpen, setSheetOpen] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ tone: "progress" | "done" | "failed"; text: string } | null>(
    null
  );
  const [scope, setScope] = useState<"me" | "all">("me");
  const retryPayloads = useRef<Record<string, Record<string, unknown>>>({});

  const refresh = useCallback(async () => {
    try {
      const data = await api.get(shop(`/day/?staff=${scope}`));
      setDay(data);
      setFetchedAt(new Date());
    } catch {
      // Silent. The banner below is the report; a toast on every failed poll
      // on a shop's patchy connection would be noise the staff member learns
      // to ignore, and then misses the one that matters.
    }
  }, [shop, scope]);

  useEffect(() => {
    refresh();
    const poll = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(poll);
  }, [refresh]);

  // The clock the bands and the elapsed counter run on.
  useEffect(() => {
    const tick = setInterval(() => setNow(new Date()), 15_000);
    return () => clearInterval(tick);
  }, []);

  const rows = useMemo(() => {
    const settled = day?.appointments ?? [];
    const settledIds = new Set(settled.map((a) => a.id));
    return [...settled, ...drafts.filter((d) => !settledIds.has(d.id))].sort(
      (a, b) => +new Date(a.starts_at) - +new Date(b.starts_at)
    );
  }, [day, drafts]);

  const bands = groupByBand(rows, now);
  const stale = fetchedAt !== null && now.getTime() - fetchedAt.getTime() > STALE_AFTER_MS;

  function settle(draftId: string, appointment: Appointment) {
    delete retryPayloads.current[draftId];
    setDrafts((current) => current.filter((d) => d.id !== draftId));
    setDay((current) =>
      current
        ? { ...current, appointments: [...current.appointments.filter((a) => a.id !== appointment.id), appointment] }
        : current
    );
    setToast({ tone: "done", text: "Saved." });
    refresh();
  }

  function fail(draftId: string, reason: string) {
    if (!reason) {
      // A collision: nothing was written, so the optimistic row is a lie and
      // goes. The sheet is already showing the choice.
      setDrafts((current) => current.filter((d) => d.id !== draftId));
      return;
    }
    setDrafts((current) =>
      current.map((d) => (d.id === draftId ? { ...d, pending: "failed", pendingDetail: reason } : d))
    );
    setToast({ tone: "failed", text: "Couldn't save that walk-in." });
  }

  async function transition(appointment: Appointment, status: string) {
    setToast({ tone: "progress", text: "Saving…" });
    try {
      const updated = await postWithRetry(shop(`/appointments/${appointment.id}/status/`), {
        status,
      });
      setDay((current) =>
        current
          ? {
              ...current,
              appointments: current.appointments.map((a) => (a.id === updated.id ? updated : a)),
            }
          : current
      );
      setToast({ tone: "done", text: "Done." });
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        // The 11:05 / 11:07 case. Name what took the chair — the staff member
        // is looking at two real people.
        const taken = error.body?.taken_by;
        setToast({
          tone: "failed",
          text: taken
            ? `That time is ${taken.client_name || taken.service_name} now.`
            : error.message,
        });
      } else {
        setToast({ tone: "failed", text: "Couldn't save that. Try again." });
      }
      refresh();
    }
  }

  useEffect(() => {
    if (!toast) return;
    const clear = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(clear);
  }, [toast]);

  const open = rows.find((a) => a.id === openId) ?? null;

  return (
    <main style={{ maxWidth: 480, margin: "0 auto", paddingBottom: 120 }}>
      <header style={{ padding: "var(--bn-space-9) var(--bn-space-gutter) var(--bn-space-7)" }}>
        <h1
          style={{
            fontFamily: "var(--bn-font-display)",
            fontSize: "var(--bn-text-display-sm-size)",
            margin: 0,
          }}
        >
          {day?.me?.display_name ?? "Today"} · today
        </h1>
        <p style={{ color: "var(--bn-ink-45)", margin: "var(--bn-space-2) 0 0" }}>
          {day?.shop.name}
        </p>
        {day?.can_view_shop && (
          <div style={{ display: "flex", gap: "var(--bn-space-4)", marginTop: "var(--bn-space-6)" }}>
            {/* Same screen, wider scope — see scheduling/views.py. A working
                owner defaults to their own chair because at the chair that is
                the list that beats the notebook. */}
            <Button
              variant={scope === "me" ? "primary" : "secondary"}
              onClick={() => setScope("me")}
              style={{ minHeight: 52 }}
            >
              My chair
            </Button>
            <Button
              variant={scope === "all" ? "primary" : "secondary"}
              onClick={() => setScope("all")}
              style={{ minHeight: 52 }}
            >
              Whole shop
            </Button>
          </div>
        )}
      </header>

      {stale && fetchedAt && (
        <div
          role="status"
          style={{
            margin: "0 var(--bn-space-gutter) var(--bn-space-7)",
            padding: "var(--bn-space-6) var(--bn-space-7)",
            borderRadius: "var(--bn-radius-card)",
            background: "var(--bn-info-50)",
            color: "var(--bn-info-700)",
            fontSize: "var(--bn-text-body-sm-size)",
          }}
        >
          Today’s list is from {clock(fetchedAt.toISOString())}. It will refresh by itself.
        </div>
      )}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: "var(--bn-space-4)",
          padding: "0 var(--bn-space-gutter) var(--bn-space-9)",
        }}
      >
        <Tile label="Appointments" value={String(day?.totals.appointments ?? 0)} />
        <Tile
          label="Deposits"
          value={money(day?.totals.deposit_total_kes ?? 0)}
          tint="var(--bn-pay-700)"
        />
        <Tile label="Walk-ins" value={String(day?.totals.walk_ins ?? 0)} />
      </div>

      {rows.length === 0 && day && (
        <p
          style={{
            margin: "0 var(--bn-space-gutter)",
            padding: "var(--bn-space-11)",
            border: "1.5px dashed var(--bn-border)",
            borderRadius: "var(--bn-radius-panel)",
            color: "var(--bn-ink-45)",
            textAlign: "center",
          }}
        >
          Nothing booked today. Record a walk-in with the + button.
        </p>
      )}

      {(["now", "next", "earlier"] as const).map((band) =>
        bands[band].length ? (
          <section key={band} style={{ padding: "0 var(--bn-space-gutter) var(--bn-space-9)" }}>
            <h2
              style={{
                fontSize: "var(--bn-text-label-size)",
                letterSpacing: "var(--bn-text-label-tracking)",
                textTransform: "uppercase",
                color: band === "now" ? "var(--bn-accent)" : "var(--bn-ink-45)",
                borderTop: band === "now" ? "2px solid var(--bn-accent)" : "1px solid var(--bn-line)",
                paddingTop: "var(--bn-space-5)",
                margin: "0 0 var(--bn-space-6)",
              }}
            >
              {band === "now" ? "Now" : band === "next" ? "Next" : "Earlier"}
            </h2>
            <div style={{ display: "grid", gap: "var(--bn-space-5)" }}>
              {bands[band].map((appointment) => (
                <AppointmentRow
                  key={appointment.id}
                  appointment={appointment}
                  now={now}
                  onOpen={() => setOpenId(appointment.id)}
                  onFinish={() => transition(appointment, "completed")}
                  onRetry={() => {
                    const payload = retryPayloads.current[appointment.id];
                    if (!payload) return;
                    setDrafts((current) =>
                      current.map((d) =>
                        d.id === appointment.id ? { ...d, pending: "sending" } : d
                      )
                    );
                    postWithRetry(shop("/walk-in/"), payload)
                      .then((saved) => settle(appointment.id, saved))
                      .catch(() => fail(appointment.id, "Still no connection to the shop."));
                  }}
                  onDiscard={() =>
                    setDrafts((current) => current.filter((d) => d.id !== appointment.id))
                  }
                />
              ))}
            </div>
          </section>
        ) : null
      )}

      <button
        type="button"
        aria-label="Record a walk-in"
        onClick={() => setSheetOpen(true)}
        style={{
          position: "fixed",
          right: "var(--bn-space-gutter)",
          bottom: "var(--bn-space-gutter)",
          width: 64,
          height: 64,
          borderRadius: 999,
          border: "none",
          background: "var(--bn-accent)",
          color: "#fff",
          fontSize: 30,
          boxShadow: "var(--bn-shadow-fab)",
          cursor: "pointer",
          zIndex: 30,
        }}
      >
        +
      </button>

      {sheetOpen && (
        <WalkInSheet
          shop={shop}
          onClose={() => setSheetOpen(false)}
          onOptimistic={(draft) => {
            retryPayloads.current[draft.id] = {
              service: draft.serviceId,
              staff: draft.staff_id,
              starts_at: draft.starts_at,
              duration_minutes: draft.duration_minutes,
              waiting: draft.is_waiting,
              client_request_id: draft.id,
            };
            setDrafts((current) => [...current, draft]);
          }}
          onSettled={settle}
          onFailed={fail}
        />
      )}

      {open && (
        <AppointmentDetail
          shop={shop}
          appointment={open}
          now={now}
          onClose={() => setOpenId(null)}
          onTransition={(status) => transition(open, status)}
          onSaved={(updated) => {
            setDay((current) =>
              current
                ? {
                    ...current,
                    appointments: current.appointments.map((a) =>
                      a.id === updated.id ? updated : a
                    ),
                  }
                : current
            );
          }}
        />
      )}

      {toast && <Toast tone={toast.tone}>{toast.text}</Toast>}
    </main>
  );
}

function Tile({ label, value, tint }: { label: string; value: string; tint?: string }) {
  return (
    <div
      style={{
        background: "var(--bn-surface)",
        border: "1.5px solid var(--bn-border)",
        borderRadius: "var(--bn-radius-card)",
        padding: "var(--bn-space-6)",
      }}
    >
      <div
        className="bn-money"
        style={{ fontSize: "var(--bn-text-body-lg-size)", fontWeight: 600, color: tint }}
      >
        {value}
      </div>
      <div
        style={{
          fontSize: "var(--bn-text-micro-size)",
          textTransform: "uppercase",
          letterSpacing: "var(--bn-text-micro-tracking)",
          color: "var(--bn-ink-45)",
          marginTop: 2,
        }}
      >
        {label}
      </div>
    </div>
  );
}
