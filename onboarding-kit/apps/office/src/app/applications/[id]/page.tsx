"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  api,
  type ApplicationDetail,
  statusClass,
  statusLabel,
  type Status,
} from "@/lib/onboardkit";
import { cn } from "@/lib/utils";

type ReviewAction = "start_review" | "approve" | "reject" | "return";

export default function ApplicationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [detail, setDetail] = useState<ApplicationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [modal, setModal] = useState<null | "reject" | "return">(null);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    try {
      setDetail(await api<ApplicationDetail>(`applications/${id}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load.");
    }
  }, [id]);

  useEffect(() => {
    // Fetch-on-mount: `load` sets state only after its awaited request resolves.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  async function act(action: ReviewAction, body: Record<string, string> = {}) {
    setBusy(true);
    setError(null);
    try {
      await api(`applications/${id}/review`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ action, ...body }),
      });
      setModal(null);
      setNote("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed.");
    } finally {
      setBusy(false);
    }
  }

  if (error && !detail) {
    return (
      <main className="mx-auto max-w-3xl p-6">
        <p className="text-destructive">{error}</p>
        <Link href="/queue" className="text-primary hover:underline">
          ← Back to queue
        </Link>
      </main>
    );
  }
  if (!detail) return <main className="p-6 text-muted-foreground">Loading…</main>;

  const { application: app, client, documents, events } = detail;
  const status = app.status as Status;
  const canStart = status === "submitted";
  const canDecide = status === "under_review";

  return (
    <main className="mx-auto max-w-5xl p-6">
      <Link href="/queue" className="text-sm text-primary hover:underline">
        ← Back to queue
      </Link>

      <header className="mt-3 mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{client.full_name}</h1>
          <p className="text-sm text-muted-foreground">
            {app.product_code}
            {client.client_number ? ` · ${client.client_number}` : ""}
          </p>
        </div>
        <span
          className={cn(
            "inline-block rounded-full px-3 py-1 text-sm font-medium",
            statusClass(status),
          )}
        >
          {statusLabel(status)}
        </span>
      </header>

      {error ? <p className="mb-4 text-sm text-destructive">{error}</p> : null}

      <div className="grid gap-6 md:grid-cols-2">
        {/* Client details */}
        <section className="rounded-lg border p-4">
          <h2 className="mb-3 font-medium">Client details</h2>
          <dl className="grid grid-cols-2 gap-y-2 text-sm">
            <Field label="Phone" value={client.phone} />
            <Field label="National ID" value={client.national_id_number} />
            <Field label="KRA PIN" value={client.kra_pin} />
            <Field label="Date of birth" value={client.date_of_birth} />
            <Field label="Address" value={client.address} />
            <Field label="OTP verified" value={app.otp_verified ? "Yes" : "No"} />
            <Field label="Consent" value={app.consent_given ? "Given" : "No"} />
          </dl>
        </section>

        {/* Documents */}
        <section className="rounded-lg border p-4">
          <h2 className="mb-3 font-medium">Documents</h2>
          <div className="grid grid-cols-2 gap-3">
            {documents.length === 0 ? (
              <p className="text-sm text-muted-foreground">No documents.</p>
            ) : (
              documents.map((d) => (
                <a
                  key={d.id}
                  href={d.url}
                  target="_blank"
                  rel="noreferrer"
                  className="block rounded-md border p-2 text-center hover:bg-muted/40"
                >
                  {d.thumbnail_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={d.thumbnail_url}
                      alt={d.doc_type}
                      className="mx-auto h-24 w-full rounded object-cover"
                    />
                  ) : (
                    <div className="flex h-24 items-center justify-center rounded bg-muted text-xs text-muted-foreground">
                      {d.processed ? "no preview" : "processing…"}
                    </div>
                  )}
                  <span className="mt-1 block text-xs text-muted-foreground">{d.doc_type}</span>
                </a>
              ))
            )}
          </div>
        </section>
      </div>

      {/* History */}
      <section className="mt-6 rounded-lg border p-4">
        <h2 className="mb-3 font-medium">History</h2>
        <ol className="space-y-2 text-sm">
          {events.map((e, i) => (
            <li key={i} className="flex justify-between border-b pb-1 last:border-0">
              <span>
                {e.from_status ? `${e.from_status} → ` : ""}
                <span className="font-medium">{e.to_status}</span>
                {e.reason ? <span className="text-muted-foreground"> — {e.reason}</span> : null}
              </span>
              <span className="text-muted-foreground">
                {new Date(e.created_at).toLocaleString()}
              </span>
            </li>
          ))}
        </ol>
      </section>

      {/* Actions */}
      {(canStart || canDecide) && (
        <div className="mt-6 flex flex-wrap gap-3">
          {canStart && (
            <Button disabled={busy} onClick={() => act("start_review")}>
              Start review
            </Button>
          )}
          {canDecide && (
            <>
              <Button disabled={busy} onClick={() => act("approve")}>
                Approve
              </Button>
              <Button variant="outline" disabled={busy} onClick={() => setModal("return")}>
                Return
              </Button>
              <Button variant="destructive" disabled={busy} onClick={() => setModal("reject")}>
                Reject
              </Button>
            </>
          )}
        </div>
      )}

      {/* Reason / notes modal */}
      {modal && (
        <div className="fixed inset-0 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-lg bg-background p-5 shadow-lg">
            <h3 className="mb-2 font-medium">
              {modal === "reject" ? "Reject application" : "Return for correction"}
            </h3>
            <p className="mb-3 text-sm text-muted-foreground">
              {modal === "reject"
                ? "A rejection reason is required and is sent to the client."
                : "Explain what the agent must correct. Sent to the client."}
            </p>
            <textarea
              className="mb-4 h-24 w-full rounded-md border p-2 text-sm"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={modal === "reject" ? "Reason…" : "Correction notes…"}
            />
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => {
                  setModal(null);
                  setNote("");
                }}
              >
                Cancel
              </Button>
              <Button
                variant={modal === "reject" ? "destructive" : "default"}
                disabled={busy || note.trim().length === 0}
                onClick={() =>
                  modal === "reject"
                    ? act("reject", { reason: note })
                    : act("return", { notes: note })
                }
              >
                Confirm
              </Button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

function Field({ label, value }: { label: string; value: string | null }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right font-medium">{value ?? "—"}</dd>
    </>
  );
}
