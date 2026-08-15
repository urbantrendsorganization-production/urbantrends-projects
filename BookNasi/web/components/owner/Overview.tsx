"use client";

/**
 * The owner dashboard. Desktop and tablet, 1024 px and up.
 *
 * ## Accent discipline
 *
 * CLAUDE.md §10 and the design handoff are explicit: **this screen has no
 * primary action and therefore no clay button at all.** Clay appears only as
 * data bars. There is nothing here to move forward — an owner reads this and
 * closes it — and a filled accent button would be the eye's first stop on a
 * screen whose whole job is to be read.
 *
 * ## Every rate is printed with its denominator
 *
 * `7.1 % of 441 finished bookings`, not `7.1 %`. An owner who disagrees with a
 * number should be able to check it, and a rate with no denominator is the
 * shape of statistic that gets argued with once and then ignored.
 *
 * ## The bars are decoration
 *
 * Utilisation and load are printed as text *and* drawn as a bar. The bar is
 * `aria-hidden` and the number is the content — which is also what lets it be
 * 8 px tall without violating the 52 px target floor, since it is not
 * interactive and not reachable. `check-invariants.mjs` reads `aria-hidden` for
 * exactly this.
 */

import { money } from "@booknasi/booking-core";

import { barWidth, hours, movement, percent, range } from "./format";
import { headlineFor } from "./headline";

export type Report = {
  period: {
    starts_on: string;
    ends_on: string;
    days: number;
    previous: { starts_on: string; ends_on: string; days: number };
  };
  scope: {
    organization_id: string;
    organization_name: string;
    shop_id: string | null;
    shops: { id: string; name: string }[];
  };
  verdict: string;
  outcomes: {
    completed: number;
    no_show: number;
    cancelled: number;
    unresolved: number;
    upcoming: number;
    total: number;
  };
  no_show: {
    rate: number | null;
    counted_out_of: number;
    previous_rate: number | null;
    previous_counted_out_of: number;
  };
  revenue_kes: number;
  money: {
    collected_kes: number;
    forfeited_kes: number;
    credit_issued_kes: number;
    refund_due_kes: number;
    pushes: number;
    pushes_succeeded: number;
    stk_completion: number | null;
  };
  clients: {
    seen: number;
    repeat: number;
    repeat_rate: number | null;
    attributed: number;
    completed: number;
    attributed_share: number | null;
  };
  staff: StaffRow[];
  today: ShopToday[];
};

export type StaffRow = {
  staff_id: string;
  display_name: string;
  shop_id: string;
  shop_name: string;
  services: number;
  revenue_kes: number;
  deposits_kes: number;
  no_shows: number;
  unresolved: number;
  shortened: number;
  booked_minutes: number;
  capacity_minutes: number;
  utilisation: number | null;
};

export type ShopToday = {
  shop_id: string;
  shop_name: string;
  appointments: number;
  walk_ins: number;
  booked_minutes: number;
  capacity_minutes: number;
  load: number | null;
};

export function Overview({
  report,
  onShop,
}: {
  report: Report;
  onShop?: (shopId: string | null) => void;
}) {
  return (
    <div style={{ display: "grid", gap: "var(--bn-space-9)" }}>
      <Headline report={report} />
      <div
        style={{
          display: "grid",
          gap: "var(--bn-space-7)",
          gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
        }}
      >
        <NoShowCard report={report} />
        <DepositCard report={report} />
        <ClientsCard report={report} />
      </div>
      <TodayAcrossShops report={report} onShop={onShop} />
      <Completeness report={report} />
      <StaffTable rows={report.staff} />
    </div>
  );
}

function Headline({ report }: { report: Report }) {
  const copy = headlineFor(report.verdict);
  const colour =
    copy.tone === "pay"
      ? "var(--bn-pay-700)"
      : copy.tone === "fail"
        ? "var(--bn-fail-700)"
        : "var(--bn-ink)";
  return (
    <header style={{ display: "grid", gap: "var(--bn-space-3)" }}>
      <h1
        style={{
          margin: 0,
          fontFamily: "var(--bn-font-display)",
          fontSize: "var(--bn-text-display-size)",
          lineHeight: "var(--bn-text-display-leading)",
          letterSpacing: "var(--bn-text-display-tracking)",
          color: colour,
        }}
      >
        {copy.headline}
      </h1>
      <p style={{ margin: 0, color: "var(--bn-ink-70)" }}>{copy.support}</p>
      <p style={{ margin: 0, color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
        {range(report.period.starts_on, report.period.ends_on)} · compared with{" "}
        {range(report.period.previous.starts_on, report.period.previous.ends_on)}
      </p>
    </header>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section
      style={{
        background: "var(--bn-surface)",
        border: "1px solid var(--bn-border)",
        borderRadius: "var(--bn-radius-card)",
        padding: "var(--bn-space-7)",
        display: "grid",
        gap: "var(--bn-space-5)",
        alignContent: "start",
      }}
    >
      <h2
        style={{
          margin: 0,
          fontSize: "var(--bn-text-label-size)",
          letterSpacing: "var(--bn-text-label-tracking)",
          textTransform: "var(--bn-label-case)" as React.CSSProperties["textTransform"],
          color: "var(--bn-ink-45)",
        }}
      >
        {title}
      </h2>
      {children}
    </section>
  );
}

function Figure({
  value,
  note,
  tone = "ink",
}: {
  value: string;
  note?: string;
  tone?: "ink" | "pay" | "fail";
}) {
  const colour =
    tone === "pay" ? "var(--bn-pay-700)" : tone === "fail" ? "var(--bn-fail-700)" : "var(--bn-ink)";
  return (
    <div>
      <div
        className="bn-money"
        style={{
          fontSize: "var(--bn-text-display-sm-size)",
          lineHeight: "var(--bn-text-display-sm-leading)",
          color: colour,
        }}
      >
        {value}
      </div>
      {note ? (
        <div style={{ color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
          {note}
        </div>
      ) : null}
    </div>
  );
}

function NoShowCard({ report }: { report: Report }) {
  const { rate, counted_out_of, previous_rate, previous_counted_out_of } = report.no_show;
  const direction = movement(rate, previous_rate);
  return (
    <Card title="No-shows">
      <Figure
        value={percent(rate)}
        note={
          counted_out_of
            ? `of ${counted_out_of} finished bookings`
            : "no finished bookings in this period"
        }
        tone={direction === "down" ? "pay" : direction === "up" ? "fail" : "ink"}
      />
      {/*
        The comparison the design draws as "before vs after deposits" — except
        that "before" is the shop's notebook and we were not there. This is the
        honest version: the shop against its own preceding period, with the
        dates printed in the header so nobody reads it as something else. See
        reporting/period.py.
      */}
      <p style={{ margin: 0, color: "var(--bn-ink-70)" }}>
        {previous_counted_out_of
          ? `${percent(previous_rate)} in the period before, of ${previous_counted_out_of}.`
          : "There is nothing in the period before this one to compare against."}
      </p>
    </Card>
  );
}

function DepositCard({ report }: { report: Report }) {
  const { collected_kes, forfeited_kes, credit_issued_kes, refund_due_kes, stk_completion, pushes } =
    report.money;
  return (
    <Card title="Deposits">
      <Figure value={money(collected_kes)} note="collected on this period's bookings" tone="pay" />
      {/*
        CLAUDE.md §1: the deposit is the product. This is the number that says
        so — what a missed appointment left behind instead of costing the full
        chair.
      */}
      <Row label="Kept from no-shows" value={money(forfeited_kes)} />
      <Row label="Turned into credit" value={money(credit_issued_kes)} />
      {refund_due_kes > 0 ? <Row label="Refunds you owe" value={money(refund_due_kes)} /> : null}
      <Row
        label="M-Pesa prompts completed"
        value={pushes ? `${percent(stk_completion, 0)} of ${pushes}` : "—"}
      />
    </Card>
  );
}

function ClientsCard({ report }: { report: Report }) {
  const { seen, repeat, repeat_rate, attributed, completed, attributed_share } = report.clients;
  return (
    <Card title="Repeat clients">
      <Figure value={percent(repeat_rate, 0)} note={seen ? `${repeat} of ${seen} came back` : "—"} />
      {/*
        The honesty line. A walk-in carries no client record — asking for a name
        at the chair is friction §4 forbids — so on a walk-in-heavy shop this
        rate describes a minority of the trade, and the screen has to say which.
      */}
      <p style={{ margin: 0, color: "var(--bn-ink-70)" }}>
        {completed
          ? `Counted over the ${attributed} of ${completed} finished bookings that carry a client ` +
            `name (${percent(attributed_share, 0)}). Walk-ins usually do not.`
          : "No finished bookings in this period."}
      </p>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--bn-space-5)" }}>
      <span style={{ color: "var(--bn-ink-70)" }}>{label}</span>
      <span className="bn-money">{value}</span>
    </div>
  );
}

function Meter({ fraction }: { fraction: number | null }) {
  return (
    <div
      aria-hidden="true"
      style={{
        background: "var(--bn-track)",
        borderRadius: "var(--bn-radius-pill)",
        height: 8,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          width: barWidth(fraction),
          height: "100%",
          background: "var(--bn-clay-600)",
        }}
      />
    </div>
  );
}

function TodayAcrossShops({
  report,
  onShop,
}: {
  report: Report;
  onShop?: (shopId: string | null) => void;
}) {
  return (
    <section style={{ display: "grid", gap: "var(--bn-space-5)" }}>
      <h2
        style={{
          margin: 0,
          fontFamily: "var(--bn-font-display)",
          fontSize: "var(--bn-text-title-size)",
        }}
      >
        Today
      </h2>
      <div
        style={{
          display: "grid",
          gap: "var(--bn-space-6)",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
        }}
      >
        {report.today.map((shop) => {
          const selected = report.scope.shop_id === shop.shop_id;
          return (
            <button
              key={shop.shop_id}
              type="button"
              onClick={() => onShop?.(selected ? null : shop.shop_id)}
              style={{
                // No clay fill: selection is a border and a tint, per the
                // design's accent discipline. This screen has no primary action.
                minHeight: "var(--bn-target-control)",
                textAlign: "left",
                cursor: onShop ? "pointer" : "default",
                background: selected ? "var(--bn-clay-50)" : "var(--bn-surface)",
                border: `${selected ? 2 : 1}px solid ${
                  selected ? "var(--bn-clay-600)" : "var(--bn-border)"
                }`,
                borderRadius: "var(--bn-radius-card)",
                padding: "var(--bn-space-6)",
                display: "grid",
                gap: "var(--bn-space-4)",
                font: "inherit",
                color: "inherit",
              }}
            >
              <div style={{ fontWeight: 600 }}>{shop.shop_name}</div>
              <Meter fraction={shop.load} />
              <div style={{ color: "var(--bn-ink-70)", fontSize: "var(--bn-text-body-sm-size)" }}>
                {shop.capacity_minutes
                  ? `${percent(shop.load, 0)} of the day booked`
                  : "Closed today"}
              </div>
              <div style={{ color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
                {shop.appointments} booked · {shop.walk_ins} walk-in
                {shop.walk_ins === 1 ? "" : "s"}
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}

/**
 * The caveat, on the screen rather than in a footnote.
 *
 * Bookings nobody pressed Finish on are missing from revenue, from utilisation
 * and from the no-show rate. A shop where a third of the period is unresolved
 * is being shown numbers that are wrong by a third, and the honest response is
 * to say so next to them.
 */
function Completeness({ report }: { report: Report }) {
  const { unresolved } = report.outcomes;
  if (!unresolved) return null;
  return (
    <p
      style={{
        margin: 0,
        background: "var(--bn-info-50)",
        color: "var(--bn-info-700)",
        border: "1px solid var(--bn-info-600)",
        borderRadius: "var(--bn-radius-md)",
        padding: "var(--bn-space-6)",
      }}
    >
      {unresolved} booking{unresolved === 1 ? "" : "s"} in this period {unresolved === 1 ? "was" : "were"}{" "}
      never finished or marked missed, so {unresolved === 1 ? "it is" : "they are"} not in the
      figures above.
    </p>
  );
}

/**
 * The revenue-per-staff table.
 *
 * Column order is the design's and it is load-bearing: **deposits and no-shows
 * stay adjacent**, because the barber with no deposits is the one with seven
 * no-shows and the table's whole argument is that you can see it in one glance.
 *
 * `Billed` and `Deposits` are two different questions and are never summed.
 * The first is `price_snapshot` on completed work — what the shop charged. The
 * second is the part that arrived by M-Pesa. Balance collection is out of v1
 * (§12), so nothing here claims to know that the rest was paid.
 */
function StaffTable({ rows }: { rows: StaffRow[] }) {
  const anyShortened = rows.some((row) => row.shortened > 0);
  return (
    <section style={{ display: "grid", gap: "var(--bn-space-5)" }}>
      <h2
        style={{
          margin: 0,
          fontFamily: "var(--bn-font-display)",
          fontSize: "var(--bn-text-title-size)",
        }}
      >
        By stylist
      </h2>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 720 }}>
          <thead>
            <tr style={{ textAlign: "left", color: "var(--bn-ink-45)" }}>
              <Th>Stylist</Th>
              <Th align="right">Services</Th>
              <Th align="right">Billed</Th>
              <Th align="right">Deposits</Th>
              <Th align="right">No-shows</Th>
              <Th>Utilisation</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.staff_id} style={{ borderTop: "1px solid var(--bn-line)" }}>
                <Td>
                  <div style={{ fontWeight: 600 }}>{row.display_name}</div>
                  <div
                    style={{ color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}
                  >
                    {row.shop_name}
                    {row.shortened ? ` · ${row.shortened} shortened` : ""}
                  </div>
                </Td>
                <Td align="right">{row.services}</Td>
                <Td align="right" mono>
                  {money(row.revenue_kes)}
                </Td>
                <Td align="right" mono>
                  {money(row.deposits_kes)}
                </Td>
                <Td align="right">{row.no_shows}</Td>
                <Td>
                  <div style={{ display: "grid", gap: "var(--bn-space-2)", minWidth: 160 }}>
                    <Meter fraction={row.utilisation} />
                    <span
                      style={{ color: "var(--bn-ink-70)", fontSize: "var(--bn-text-body-sm-size)" }}
                    >
                      {row.capacity_minutes
                        ? `${percent(row.utilisation, 0)} · ${hours(row.booked_minutes)} of ${hours(
                            row.capacity_minutes
                          )}`
                        : "Not rostered"}
                    </span>
                  </div>
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {anyShortened ? (
        /*
          `Appointment.was_shortened`'s own comment asks for this. A walk-in
          recorded short at full price books fewer minutes for the same money,
          which deflates utilisation and would flatter any revenue-per-hour
          figure. Shown next to the number rather than absorbed into it.
        */
        <p style={{ margin: 0, color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
          Shortened walk-ins are charged in full but book less chair time, so they pull utilisation
          down.
        </p>
      ) : null}
    </section>
  );
}

function Th({ children, align }: { children: React.ReactNode; align?: "right" }) {
  return (
    <th
      style={{
        padding: "var(--bn-space-4) var(--bn-space-5)",
        textAlign: align ?? "left",
        fontSize: "var(--bn-text-label-size)",
        letterSpacing: "var(--bn-text-label-tracking)",
        textTransform: "var(--bn-label-case)" as React.CSSProperties["textTransform"],
        fontWeight: 600,
      }}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  align,
  mono,
}: {
  children: React.ReactNode;
  align?: "right";
  mono?: boolean;
}) {
  return (
    <td
      className={mono ? "bn-money" : undefined}
      style={{
        padding: "var(--bn-space-5)",
        textAlign: align ?? "left",
        verticalAlign: "middle",
      }}
    >
      {children}
    </td>
  );
}
