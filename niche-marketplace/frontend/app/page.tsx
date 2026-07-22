import { getHealth } from "@/lib/api";

// Server component: fetches the backend healthcheck on the server and renders
// its status. This proves the frontend can reach the API end-to-end.
export default async function Home() {
  const health = await getHealth();
  const online = health?.status === "ok";

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-8 px-6 py-16">
      <header className="space-y-2">
        <h1 className="text-3xl font-bold tracking-tight text-brand">Marketplace</h1>
        <p className="text-sm text-neutral-500">
          Buy and sell locally — a portfolio classifieds project.
        </p>
      </header>

      <section className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
            API status
          </h2>
          <span
            className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium ${
              online
                ? "bg-green-100 text-green-700"
                : "bg-red-100 text-red-700"
            }`}
          >
            <span
              className={`h-2 w-2 rounded-full ${
                online ? "bg-green-500" : "bg-red-500"
              }`}
              aria-hidden
            />
            {online ? "Online" : "Unreachable"}
          </span>
        </div>

        {health ? (
          <dl className="mt-4 grid grid-cols-2 gap-y-3 text-sm">
            <dt className="text-neutral-500">Status</dt>
            <dd className="text-right font-medium">{health.status}</dd>

            <dt className="text-neutral-500">Version</dt>
            <dd className="text-right font-medium">{health.version}</dd>

            <dt className="text-neutral-500">Database</dt>
            <dd className="text-right font-medium">{health.services.database}</dd>

            <dt className="text-neutral-500">Redis</dt>
            <dd className="text-right font-medium">{health.services.redis}</dd>
          </dl>
        ) : (
          <p className="mt-4 text-sm text-neutral-500">
            Could not reach the backend at <code>/api/v1/health/</code>. Is the
            API running?
          </p>
        )}
      </section>
    </main>
  );
}
