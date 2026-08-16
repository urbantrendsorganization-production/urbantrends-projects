"use client";

/**
 * Data & privacy — the design's fourth settings section, and CLAUDE.md §9's
 * export and delete paths where somebody can actually reach them.
 *
 * ## The screen leads with what is owed, not with a search box
 *
 * A client who asked to be forgotten has a statutory clock running, and the
 * shop is the controller. So outstanding requests are the top of the screen and
 * everything else is below them. A search box first would be a screen that only
 * helps somebody who already knows they have something to do.
 *
 * ## Erasing is owner-only, and a manager is told rather than blocked silently
 *
 * `POST .../erase/` is `owner_role_required`. A manager can see the list and
 * the requests — they will be the ones fielding the phone call — and gets a
 * sentence where the button would be. Hiding the requests from them instead
 * would mean the person most likely to hear about it is the one who cannot see
 * it.
 *
 * ## The cost is stated before the confirm, from the server
 *
 * Erasure voids unspent credit, and nobody would guess that. `GET .../erase/`
 * returns the amount and the visit count, and the dialog words what the server
 * computed rather than recomputing it — the same split as the readiness
 * checklist and the dashboard verdict.
 */

import { useState } from "react";

import { ApiError, api } from "../../lib/api";
import { firstError } from "../../lib/auth";
import { Button, Empty, ErrorPanel, Note, Section, TextInput } from "./primitives";

export type ClientRow = {
  id: string;
  full_name: string;
  phone: string;
  is_erased: boolean;
  scrubbed_at: string | null;
  scrub_reason: string;
  erasure_requested_at: string | null;
  last_seen: string | null;
  visits: number | null;
};

type Plan = { appointments: number; credit_kes: number; already_erased: boolean };

export function PrivacyEditor({
  orgId,
  clients,
  retentionStatement,
  canErase,
  onChanged,
}: {
  orgId: string;
  clients: ClientRow[];
  retentionStatement: string;
  canErase: boolean;
  onChanged: () => void;
}) {
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState<{ row: ClientRow; plan: Plan } | null>(null);
  const [busy, setBusy] = useState(false);

  const requested = clients.filter((row) => row.erasure_requested_at && !row.is_erased);
  const needle = query.trim().toLowerCase();
  const matches = needle
    ? clients.filter(
        (row) =>
          row.full_name.toLowerCase().includes(needle) || row.phone.includes(needle)
      )
    : clients.slice(0, 20);

  function askToErase(row: ClientRow) {
    setError("");
    api
      .get(`/api/v1/orgs/${orgId}/clients/${row.id}/erase/`)
      .then((plan) => setConfirming({ row, plan }))
      .catch(() => setError("Could not check what that would remove."));
  }

  function erase() {
    if (!confirming) return;
    setBusy(true);
    api
      .post(`/api/v1/orgs/${orgId}/clients/${confirming.row.id}/erase/`, {})
      .then(() => {
        setConfirming(null);
        onChanged();
      })
      .catch((caught) =>
        setError(
          caught instanceof ApiError
            ? firstError(caught.body, "Could not erase that record.")
            : "Could not erase that record."
        )
      )
      .finally(() => setBusy(false));
  }

  return (
    <>
      <Section
        id="setup-privacy"
        title="Requests to be forgotten"
        intro="Clients can ask through the link in their booking SMS. The law gives you a deadline from the day they ask, not the day you look."
      >
        <ErrorPanel>{error}</ErrorPanel>

        {requested.length ? (
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: "var(--bn-space-4)" }}>
            {requested.map((row) => (
              <li key={row.id}>
                <Person
                  row={row}
                  orgId={orgId}
                  canErase={canErase}
                  onErase={() => askToErase(row)}
                  highlight
                />
              </li>
            ))}
          </ul>
        ) : (
          <Empty title="Nothing outstanding">
            <Note>Requests appear here as soon as a client makes one.</Note>
          </Empty>
        )}
      </Section>

      <Section
        title="Everyone on your books"
        intro="Search by name or number. You can give someone a copy of everything you hold about them, or remove it."
      >
        <TextInput value={query} onChange={setQuery} placeholder="Name or phone number" />

        {matches.length ? (
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: "var(--bn-space-4)" }}>
            {matches.map((row) => (
              <li key={row.id}>
                <Person
                  row={row}
                  orgId={orgId}
                  canErase={canErase}
                  onErase={() => askToErase(row)}
                />
              </li>
            ))}
          </ul>
        ) : (
          <Empty title="Nobody matches that" />
        )}

        {!needle && clients.length > matches.length ? (
          <Note>
            Showing {matches.length} of {clients.length}. Search to find anyone else.
          </Note>
        ) : null}
      </Section>

      <Section
        title="How long you keep things"
        intro="This is the sentence your clients are shown. It is not editable here — it is what the system actually does."
      >
        {/*
          Rendered from the server's own wording, never restated. Same rule as
          §12's refund sentence: a policy worded in two places is a policy a
          shop can state one way to a client and another way to itself.
        */}
        <p
          style={{
            margin: 0,
            padding: "var(--bn-space-6)",
            borderRadius: "var(--bn-radius-md)",
            border: "1px solid var(--bn-line)",
            background: "var(--bn-canvas)",
            textWrap: "pretty",
          }}
        >
          {retentionStatement}
        </p>
        <Note>
          Bookings stay in your records after a client is removed, with their name and number taken
          out — so your revenue, no-show rate and busiest-day figures do not change.
        </Note>
      </Section>

      {confirming ? (
        <ConfirmErasure
          row={confirming.row}
          plan={confirming.plan}
          busy={busy}
          onCancel={() => setConfirming(null)}
          onConfirm={erase}
        />
      ) : null}
    </>
  );
}

function Person({
  row,
  orgId,
  canErase,
  onErase,
  highlight = false,
}: {
  row: ClientRow;
  orgId: string;
  canErase: boolean;
  onErase: () => void;
  highlight?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "var(--bn-space-6)",
        flexWrap: "wrap",
        padding: "var(--bn-space-5) var(--bn-space-6)",
        borderRadius: "var(--bn-radius-md)",
        border: highlight ? "1.5px solid var(--bn-accent)" : "1px solid var(--bn-line)",
        background: row.is_erased ? "var(--bn-canvas)" : "var(--bn-surface)",
      }}
    >
      <span style={{ display: "grid", gap: "var(--bn-space-2)", minWidth: 0 }}>
        <span style={{ fontWeight: 600, color: row.is_erased ? "var(--bn-ink-45)" : "var(--bn-ink)" }}>
          {row.is_erased ? "Removed" : row.full_name || "No name recorded"}
        </span>
        <span style={{ color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
          {row.is_erased
            ? `Their details were removed. ${row.visits ?? 0} past ${
                row.visits === 1 ? "booking is" : "bookings are"
              } still in your records without them.`
            : [
                row.phone,
                row.visits ? `${row.visits} ${row.visits === 1 ? "visit" : "visits"}` : "No visits yet",
              ]
                .filter(Boolean)
                .join(" · ")}
        </span>
      </span>

      <span style={{ display: "flex", gap: "var(--bn-space-4)", flexWrap: "wrap" }}>
        {/*
          A plain link, not a fetch. The response is a file with a
          `Content-Disposition`, and letting the browser handle it is what makes
          it land in a downloads folder rather than in a blob somebody has to be
          given a button to save.
        */}
        <a
          href={`/api/v1/orgs/${orgId}/clients/${row.id}/export/`}
          style={{
            minHeight: "var(--bn-target-control)",
            display: "inline-flex",
            alignItems: "center",
            padding: "0 var(--bn-space-6)",
            borderRadius: "var(--bn-radius-md)",
            border: "1.5px solid var(--bn-border)",
            color: "var(--bn-ink)",
            textDecoration: "none",
            fontWeight: 600,
          }}
        >
          Export
        </a>

        {row.is_erased ? null : canErase ? (
          <Button
            variant="quiet"
            onClick={onErase}
            style={{ width: "auto", padding: "0 var(--bn-space-6)" }}
          >
            Remove
          </Button>
        ) : (
          <span
            style={{
              alignSelf: "center",
              color: "var(--bn-ink-45)",
              fontSize: "var(--bn-text-body-sm-size)",
            }}
          >
            Only the owner can remove
          </span>
        )}
      </span>
    </div>
  );
}

/**
 * The confirm, wording what the server computed.
 *
 * Everything here is a number the API returned. A dialog that guessed at the
 * credit, or left it out, would be asking somebody to agree to something nobody
 * had told them — and the credit is the part they would only discover when a
 * client next tried to spend it.
 */
function ConfirmErasure({
  row,
  plan,
  busy,
  onCancel,
  onConfirm,
}: {
  row: ClientRow;
  plan: Plan;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <Section title="Remove this person's details?">
      <p style={{ margin: 0, textWrap: "pretty" }}>
        <strong>{row.full_name || row.phone || "This client"}</strong>&rsquo;s name, phone number and
        notes will be permanently removed. This cannot be undone.
      </p>

      <ul style={{ margin: 0, paddingLeft: "1.2em", display: "grid", gap: "var(--bn-space-3)" }}>
        <li>
          {plan.appointments} {plan.appointments === 1 ? "booking stays" : "bookings stay"} in your
          records, without their details. Your figures do not change.
        </li>
        {plan.credit_kes > 0 ? (
          <li style={{ color: "var(--bn-fail-700)" }}>
            They hold <strong>KES {plan.credit_kes.toLocaleString()}</strong> in credit at your shop.
            Removing their details voids it — credit is paid out to a phone number, and there will
            not be one.
          </li>
        ) : null}
      </ul>

      <div style={{ display: "flex", gap: "var(--bn-space-6)", flexWrap: "wrap" }}>
        <Button onClick={onConfirm} disabled={busy} style={{ width: "auto" }}>
          {busy ? "Removing…" : "Remove their details"}
        </Button>
        <Button
          variant="quiet"
          onClick={onCancel}
          disabled={busy}
          style={{ width: "auto", padding: "0 var(--bn-space-6)" }}
        >
          Keep them
        </Button>
      </div>
    </Section>
  );
}
