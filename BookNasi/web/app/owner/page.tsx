"use client";

/**
 * `/owner` — the dashboard, from one `/me/` call and one report call.
 *
 * ## Owners and managers only, on both sides
 *
 * The API refuses a stylist with a 403 (`reporting/views.py`), which is the
 * control that matters. This page also declines to *offer* the tab to a
 * membership that is not owner or manager, because a link that always 403s is
 * a link that reads as broken software rather than as a boundary.
 *
 * ## Desktop and tablet, 1024 px and up
 *
 * The handoff is explicit: below that, the staff view is the correct
 * experience. A narrow viewport is sent there rather than being served a
 * squeezed table — an owner on their phone in the shop wants today's list, not
 * a utilisation column they cannot read.
 *
 * ## No skeleton, no auto-refresh
 *
 * "Owner view: date range, shop scope, cached aggregates — no realtime
 * requirement." Nothing here polls. The range picker is the only thing that
 * refetches, and it says when the numbers were fetched so a stale tab is
 * legible rather than misleading.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { Overview, type Report } from "../../components/owner/Overview";
import { ApiError, api } from "../../lib/api";

type Membership = {
  organization: string;
  organization_name: string;
  role: "owner" | "manager" | "staff";
};

/** The presets the design's range picker offers. Absolute dates are computed
 *  in EAT, because the report's days are EAT calendar dates. */
const PRESETS = [
  { label: "Last 7 days", days: 7 },
  { label: "Last 30 days", days: 30 },
  { label: "Last 90 days", days: 90 },
];

function eatToday(): Date {
  const now = new Date();
  return new Date(now.toLocaleString("en-US", { timeZone: "Africa/Nairobi" }));
}

function isoDay(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function rangeFor(days: number) {
  const to = eatToday();
  const from = new Date(to);
  from.setDate(from.getDate() - (days - 1));
  return { from: isoDay(from), to: isoDay(to) };
}

export default function OwnerDashboard() {
  const [memberships, setMemberships] = useState<Membership[] | null>(null);
  const [org, setOrg] = useState<Membership | null>(null);
  const [days, setDays] = useState(30);
  const [shopId, setShopId] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [fetchedAt, setFetchedAt] = useState<Date | null>(null);

  useEffect(() => {
    api
      .get("/api/v1/auth/me/")
      .then((data) => {
        const managing = (data.memberships as Membership[]).filter(
          (row) => row.role === "owner" || row.role === "manager"
        );
        setMemberships(managing);
        if (managing.length === 1) setOrg(managing[0]);
      })
      // Not signed in is not an error to display — it is a destination. Both
      // dashboards said "Sign in to see your dashboard" from the day they
      // shipped, with nowhere to do it, because `/signin` did not exist until
      // slice 11. A 401 or 403 here means the session is gone or was never
      // there, and the honest response is the front door.
      .catch((caught) => {
        if (caught instanceof ApiError && (caught.status === 401 || caught.status === 403)) {
          window.location.assign("/signin");
          return;
        }
        setError("Could not reach the dashboard. Check your connection.");
      });
  }, []);

  const load = useCallback(() => {
    if (!org) return;
    const { from, to } = rangeFor(days);
    const query = new URLSearchParams({ from, to });
    if (shopId) query.set("shop", shopId);
    api
      .get(`/api/v1/orgs/${org.organization}/report/?${query}`)
      .then((data) => {
        setReport(data);
        setFetchedAt(new Date());
        setError("");
      })
      .catch((caught) => {
        setReport(null);
        setError(
          caught?.status === 403
            ? "Only an owner or a manager can see this."
            : "That did not load. Try again."
        );
      });
  }, [org, days, shopId]);

  useEffect(load, [load]);

  const shops = useMemo(() => report?.scope.shops ?? [], [report]);

  if (error && !report) return <Shell>{error}</Shell>;
  if (!memberships) return <Shell>Loading…</Shell>;
  if (!memberships.length) {
    return <Shell>This dashboard is for shop owners and managers.</Shell>;
  }

  return (
    <main
      style={{
        maxWidth: 1320,
        margin: "0 auto",
        padding: "var(--bn-space-9) var(--bn-space-gutter-desktop)",
        display: "grid",
        gap: "var(--bn-space-8)",
      }}
    >
      <TopBar
        memberships={memberships}
        org={org}
        onOrg={(next) => {
          setOrg(next);
          setShopId(null);
        }}
        days={days}
        onDays={setDays}
        shops={shops}
        shopId={shopId}
        onShop={setShopId}
        fetchedAt={fetchedAt}
      />
      {/*
        The handoff's responsive rule, kept as a rule rather than a hope: below
        1024 px the staff view is the correct experience, so the table is not
        squeezed — it is replaced with the sentence that says where to go.
      */}
      <div className="bn-owner-narrow">
        Open this on a laptop or tablet. On a phone, <a href="/staff">today&apos;s list</a> is the
        screen you want.
      </div>
      <div className="bn-owner-wide">
        {report ? <Overview report={report} onShop={setShopId} /> : <Shell>Loading…</Shell>}
      </div>
      <style>{`
        .bn-owner-narrow { display: block; color: var(--bn-ink-70); }
        .bn-owner-wide { display: none; }
        @media (min-width: 1024px) {
          .bn-owner-narrow { display: none; }
          .bn-owner-wide { display: block; }
        }
      `}</style>
    </main>
  );
}

function TopBar({
  memberships,
  org,
  onOrg,
  days,
  onDays,
  shops,
  shopId,
  onShop,
  fetchedAt,
}: {
  memberships: Membership[];
  org: Membership | null;
  onOrg: (m: Membership) => void;
  days: number;
  onDays: (days: number) => void;
  shops: { id: string; name: string }[];
  shopId: string | null;
  onShop: (id: string | null) => void;
  fetchedAt: Date | null;
}) {
  return (
    <header
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: "var(--bn-space-5)",
        alignItems: "center",
        justifyContent: "space-between",
        borderBottom: "1px solid var(--bn-line)",
        paddingBottom: "var(--bn-space-6)",
      }}
    >
      <div style={{ display: "flex", gap: "var(--bn-space-5)", alignItems: "center" }}>
        <span style={{ fontFamily: "var(--bn-font-display)", fontWeight: 700 }}>BookNasi</span>
        {memberships.length > 1 ? (
          <Picker
            options={memberships.map((row) => ({
              id: row.organization,
              label: row.organization_name,
            }))}
            selected={org?.organization ?? null}
            onSelect={(id) => {
              const next = memberships.find((row) => row.organization === id);
              if (next) onOrg(next);
            }}
          />
        ) : (
          <span style={{ color: "var(--bn-ink-70)" }}>{org?.organization_name}</span>
        )}
      </div>

      <div
        style={{ display: "flex", gap: "var(--bn-space-5)", alignItems: "center", flexWrap: "wrap" }}
      >
        {shops.length > 1 ? (
          <Picker
            options={[{ id: "", label: "All shops" }, ...shops.map((s) => ({ id: s.id, label: s.name }))]}
            selected={shopId ?? ""}
            onSelect={(id) => onShop(id || null)}
          />
        ) : null}
        <Picker
          options={PRESETS.map((preset) => ({ id: String(preset.days), label: preset.label }))}
          selected={String(days)}
          onSelect={(id) => onDays(Number(id))}
        />
        {fetchedAt ? (
          <span style={{ color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
            as of{" "}
            {fetchedAt.toLocaleTimeString("en-GB", {
              timeZone: "Africa/Nairobi",
              hour: "2-digit",
              minute: "2-digit",
            })}{" "}
            EAT
          </span>
        ) : null}
      </div>
    </header>
  );
}

/**
 * A `<select>` rather than a row of buttons.
 *
 * The 52 px target floor applies to it like everything else, and a native
 * control gets keyboard and screen-reader behaviour that a div-with-onClick
 * would have to reimplement badly. There is no clay here — this screen has no
 * primary action.
 */
function Picker({
  options,
  selected,
  onSelect,
}: {
  options: { id: string; label: string }[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <select
      value={selected ?? ""}
      onChange={(event) => onSelect(event.target.value)}
      style={{
        minHeight: "var(--bn-target-control)",
        padding: "0 var(--bn-space-6)",
        borderRadius: "var(--bn-radius-md)",
        border: "1.5px solid var(--bn-border)",
        background: "var(--bn-surface)",
        color: "var(--bn-ink)",
        font: "inherit",
      }}
    >
      {options.map((option) => (
        <option key={option.id} value={option.id}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div style={{ padding: "var(--bn-space-9)", color: "var(--bn-ink-45)" }}>{children}</div>;
}
