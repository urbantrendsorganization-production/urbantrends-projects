"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api, humanDuration, type ReportSummary } from "@/lib/onboardkit";

const PIE_COLORS = [
  "#ef4444",
  "#f97316",
  "#eab308",
  "#84cc16",
  "#06b6d4",
  "#8b5cf6",
];

export default function ReportsPage() {
  const [data, setData] = useState<ReportSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api<ReportSummary>("reports/summary"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load.");
    }
  }, []);

  useEffect(() => {
    // Fetch-on-mount: `load` sets state only after its awaited request resolves.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  if (error && !data) {
    return (
      <main className="mx-auto max-w-3xl p-6">
        <p className="text-destructive">{error}</p>
        <Link href="/queue" className="text-primary hover:underline">
          ← Back to queue
        </Link>
      </main>
    );
  }
  if (!data) return <main className="p-6 text-muted-foreground">Loading…</main>;

  function download(format: "csv" | "xlsx") {
    // Route-handler download: the proxy forwards content-disposition so the
    // browser saves the file. Direct navigation carries the httpOnly cookie.
    window.location.href = `/api/proxy/exports/approved-clients?format=${format}`;
  }

  const totalOnboarded = data.per_agent.reduce((n, a) => n + a.total, 0);
  const totalApproved = data.per_agent.reduce((n, a) => n + a.approved, 0);
  const totalRejected = data.rejection_reasons.reduce((n, r) => n + r.count, 0);

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <Link href="/queue" className="text-sm text-primary hover:underline">
            ← Back to queue
          </Link>
          <h1 className="mt-1 text-2xl font-semibold">Reports</h1>
        </div>
        <div className="flex gap-2">
          <button
            className="rounded-md border px-3 py-1.5 text-sm hover:bg-muted"
            onClick={() => download("csv")}
          >
            Export CSV
          </button>
          <button
            className="rounded-md border px-3 py-1.5 text-sm hover:bg-muted"
            onClick={() => download("xlsx")}
          >
            Export Excel
          </button>
        </div>
      </header>

      {/* Summary cards */}
      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Onboarded" value={totalOnboarded} />
        <Stat label="Approved" value={totalApproved} />
        <Stat label="Rejected" value={totalRejected} />
        <Stat
          label="Avg. time to approval"
          value={humanDuration(data.avg_time_to_approval_secs)}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Onboardings per agent */}
        <ChartCard title="Onboardings per agent">
          {data.per_agent.length === 0 ? (
            <Empty />
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={data.per_agent} margin={{ left: -20 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="agent_name" tick={{ fontSize: 11 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend />
                <Bar dataKey="total" name="Total" fill="#94a3b8" radius={[3, 3, 0, 0]} />
                <Bar dataKey="approved" name="Approved" fill="#22c55e" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        {/* Onboardings per branch */}
        <ChartCard title="Onboardings per branch">
          {data.per_branch.length === 0 ? (
            <Empty />
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={data.per_branch} margin={{ left: -20 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="branch_name" tick={{ fontSize: 11 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="total" name="Total" fill="#3b82f6" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        {/* Rejection reasons */}
        <ChartCard title="Rejection reasons">
          {data.rejection_reasons.length === 0 ? (
            <Empty />
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie
                  data={data.rejection_reasons}
                  dataKey="count"
                  nameKey="reason"
                  cx="50%"
                  cy="50%"
                  outerRadius={90}
                  label={(e) => `${e.reason} (${e.count})`}
                  labelLine={false}
                >
                  {data.rejection_reasons.map((_, i) => (
                    <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          )}
        </ChartCard>
      </div>
    </main>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border p-4">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </div>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border p-4">
      <h2 className="mb-3 font-medium">{title}</h2>
      {children}
    </section>
  );
}

function Empty() {
  return (
    <div className="flex h-[260px] items-center justify-center text-sm text-muted-foreground">
      No data yet.
    </div>
  );
}
