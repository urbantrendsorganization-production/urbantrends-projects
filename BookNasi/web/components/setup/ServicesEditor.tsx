"use client";

/**
 * What the shop sells, and the deposit rule on each one.
 *
 * This is the screen the product is actually about. CLAUDE.md §1: "the product
 * being sold is not the calendar, it's the M-Pesa deposit" — and this is where
 * a deposit comes into existence.
 *
 * ## The 25 % pre-fill, and the design disagreeing with itself
 *
 * The design handoff says the deposit editor should default to flat KES with
 * **nothing pre-filled**, and advises "about a quarter of the price" in prose.
 * CLAUDE.md §12 settles it the other way and this follows CLAUDE.md: a new
 * service starts at 25 % of its price, because a blank field stays blank and
 * "charging nothing has to be a deliberate change rather than the path of
 * least resistance". The prose advice is kept — it is good advice — but it is
 * no longer the only thing standing between a shop and a deposit-free
 * catalogue.
 *
 * `deposit_amount` is never computed here. It arrives from the API as the
 * figure `shops/money.py` produced, for the same reason `booking-core/money.ts`
 * refuses to compute one: a client-side percentage rounds differently on some
 * price sooner or later, and then the number the client agreed to stops being
 * the number they were charged.
 *
 * ## The refund sentence is previewed, not restated
 *
 * The design asks for "a preview of the exact sentence the client will read",
 * and the only way that is worth anything is if it is the *same function*.
 * It is `refundSentence` from `booking-core`, the one place the terms are
 * worded (CLAUDE.md §12), rendered here with this shop's own numbers. A second
 * copy for the settings screen is how a shop ends up showing clients one
 * policy and its owner another.
 */

import { money, refundSentence, spellDuration } from "@booknasi/booking-core";
import { useState } from "react";

import { ApiError, api } from "../../lib/api";
import { firstError } from "../../lib/auth";
import {
  Button,
  Empty,
  ErrorPanel,
  Field,
  Grid,
  NumberInput,
  Note,
  Section,
  Select,
  TextInput,
  Toggle,
} from "./primitives";

export type Service = {
  id: string;
  name: string;
  description: string;
  duration_minutes: number;
  price: number;
  deposit_mode: "none" | "flat" | "percent";
  deposit_value: string | null;
  deposit_amount: number;
  is_active: boolean;
  is_publicly_listed: boolean;
  is_publicly_bookable: boolean;
};

type Draft = {
  name: string;
  duration_minutes: string;
  price: string;
  deposit_mode: "none" | "flat" | "percent";
  deposit_value: string;
};

/** CLAUDE.md §12's pre-fill, as the shape a new row starts in. */
const BLANK: Draft = {
  name: "",
  duration_minutes: "",
  price: "",
  deposit_mode: "percent",
  deposit_value: "25",
};

const MODES = [
  { value: "percent", label: "Percentage of the price" },
  { value: "flat", label: "Flat amount in KES" },
  { value: "none", label: "No deposit" },
];

function draftFrom(service: Service): Draft {
  return {
    name: service.name,
    duration_minutes: String(service.duration_minutes),
    price: String(service.price),
    deposit_mode: service.deposit_mode,
    deposit_value: service.deposit_value ?? "",
  };
}

function payloadFrom(draft: Draft) {
  return {
    name: draft.name,
    duration_minutes: Number(draft.duration_minutes),
    price: Number(draft.price),
    deposit_mode: draft.deposit_mode,
    // `none` carries no value at all rather than a zero — the model's own
    // validation distinguishes them, and a 0 in `flat` mode is a different
    // (and refused) thing from "no deposit rule".
    deposit_value: draft.deposit_mode === "none" ? null : draft.deposit_value || null,
  };
}

export function ServicesEditor({
  orgId,
  shopId,
  services,
  refundWindowHours,
  depositCreditDays,
  onChanged,
}: {
  orgId: string;
  shopId: string;
  services: Service[];
  refundWindowHours: number;
  depositCreditDays: number;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");

  return (
    <>
      <Section
        id="setup-services"
        title="Services and deposits"
        intro="What you sell, how long it takes, and what a client pays up front to hold the chair."
        actions={
          !adding ? (
            <Button onClick={() => { setAdding(true); setEditing(null); }} style={{ width: "auto", minWidth: 180 }}>
              Add a service
            </Button>
          ) : null
        }
      >
        <ErrorPanel>{error}</ErrorPanel>

        {adding ? (
          <ServiceRowEditor
            initial={BLANK}
            title="New service"
            onCancel={() => setAdding(false)}
            onSubmit={(draft, done) =>
              api
                .post(`/api/v1/orgs/${orgId}/shops/${shopId}/services/`, payloadFrom(draft))
                .then(() => {
                  setAdding(false);
                  onChanged();
                })
                .catch((caught) =>
                  setError(caught instanceof ApiError ? firstError(caught.body, "Could not save.") : "Could not save.")
                )
                .finally(done)
            }
          />
        ) : null}

        {services.length === 0 && !adding ? (
          <Empty title="Nothing to book yet">
            <Note>
              Start with the three or four things people actually ask for. About a quarter of the
              price is a normal deposit, and it is what a new service starts at.
            </Note>
          </Empty>
        ) : null}

        <div style={{ display: "grid", gap: "var(--bn-space-5)" }}>
          {services.map((service) =>
            editing === service.id ? (
              <ServiceRowEditor
                key={service.id}
                initial={draftFrom(service)}
                title={service.name}
                onCancel={() => setEditing(null)}
                onSubmit={(draft, done) =>
                  api
                    .patch(
                      `/api/v1/orgs/${orgId}/shops/${shopId}/services/${service.id}/`,
                      payloadFrom(draft)
                    )
                    .then(() => {
                      setEditing(null);
                      onChanged();
                    })
                    .catch((caught) =>
                      setError(
                        caught instanceof ApiError ? firstError(caught.body, "Could not save.") : "Could not save."
                      )
                    )
                    .finally(done)
                }
                onRetire={() =>
                  api
                    .del(`/api/v1/orgs/${orgId}/shops/${shopId}/services/${service.id}/`)
                    .then(() => {
                      setEditing(null);
                      onChanged();
                    })
                    .catch(() => setError("Could not retire that service."))
                }
              />
            ) : (
              <ServiceRow
                key={service.id}
                service={service}
                onEdit={() => { setEditing(service.id); setAdding(false); }}
              />
            )
          )}
        </div>
      </Section>

      <Section
        title="Cancellation terms"
        intro="Every client reads this before they pay, and again on the page their confirmation SMS links to."
      >
        <Grid min={260}>
          <Field
            label="Free cancellation up to"
            hint="Cancel earlier than this and the deposit is refunded."
          >
            <ShopNumber
              orgId={orgId}
              shopId={shopId}
              field="refund_window_hours"
              value={refundWindowHours}
              suffix="hours before"
              onChanged={onChanged}
            />
          </Field>
          <Field
            label="Late cancellation credit lasts"
            hint="A late cancellation keeps its value as credit at your shop, on any service."
          >
            <ShopNumber
              orgId={orgId}
              shopId={shopId}
              field="deposit_credit_days"
              value={depositCreditDays}
              suffix="days"
              onChanged={onChanged}
            />
          </Field>
        </Grid>

        {/*
          The exact sentence, from the one function that words it. Not a
          paraphrase — CLAUDE.md §10 lets a host translate or relabel this and
          never remove it, and §12 names `money.refundSentence` as the single
          place it exists.
        */}
        <blockquote
          style={{
            margin: 0,
            padding: "var(--bn-space-7)",
            borderRadius: "var(--bn-radius-card)",
            background: "var(--bn-pay-50)",
            color: "var(--bn-ink)",
            borderLeft: "3px solid var(--bn-pay-600)",
            textWrap: "pretty",
          }}
        >
          {refundSentence(refundWindowHours, depositCreditDays)}
        </blockquote>
        <Note>
          The last two outcomes are not yours to set: a client who does not turn up loses the
          deposit, and if you cancel it is refunded whenever you do it.
        </Note>
      </Section>
    </>
  );
}

/**
 * One shop-level number, saved on its own.
 *
 * The Save button appears only once the value differs from what is stored, so
 * the preview above updates as the owner types while the sentence clients
 * actually read changes only when they commit. The two halves of the terms are
 * separate requests because they are separate decisions.
 */
function ShopNumber({
  orgId,
  shopId,
  field,
  value,
  suffix,
  onChanged,
}: {
  orgId: string;
  shopId: string;
  field: "refund_window_hours" | "deposit_credit_days";
  value: number;
  suffix: string;
  onChanged: () => void;
}) {
  const [draft, setDraft] = useState(String(value));
  const dirty = draft !== String(value) && draft !== "";

  return (
    <span style={{ display: "flex", gap: "var(--bn-space-5)", alignItems: "center" }}>
      <NumberInput value={draft} onChange={setDraft} suffix={suffix} />
      {dirty ? (
        <Button
          onClick={() =>
            api
              .patch(`/api/v1/orgs/${orgId}/shops/${shopId}/`, { [field]: Number(draft) })
              .then(() => onChanged())
          }
          style={{ width: "auto", padding: "0 var(--bn-space-7)" }}
        >
          Save
        </Button>
      ) : null}
    </span>
  );
}

function ServiceRow({ service, onEdit }: { service: Service; onEdit: () => void }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--bn-space-6)",
        padding: "var(--bn-space-5) var(--bn-space-6)",
        border: "1px solid var(--bn-line)",
        borderRadius: "var(--bn-radius-md)",
        background: service.is_active ? "var(--bn-surface)" : "var(--bn-canvas)",
        flexWrap: "wrap",
      }}
    >
      <span style={{ display: "grid", gap: "var(--bn-space-2)", flex: 1, minWidth: 200 }}>
        <span style={{ fontWeight: 600, color: "var(--bn-ink)" }}>{service.name}</span>
        <span style={{ color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
          {spellDuration(service.duration_minutes)}
          {service.is_active ? "" : " · retired"}
        </span>
      </span>

      <span
        style={{
          fontFamily: "var(--bn-font-mono)",
          fontSize: "var(--bn-text-money-size)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {money(service.price)}
      </span>

      <DepositBadge service={service} />

      <Button variant="secondary" onClick={onEdit} style={{ width: "auto", padding: "0 var(--bn-space-7)" }}>
        Edit
      </Button>
    </div>
  );
}

/**
 * The badge says bookable or not, because that is the consequence a shop
 * cares about — "no deposit" is the cause and §5's rule is the effect, and
 * only one of them explains why the service is missing from the booking page.
 */
function DepositBadge({ service }: { service: Service }) {
  const bookable = service.is_publicly_bookable;
  return (
    <span
      style={{
        display: "inline-grid",
        gap: "var(--bn-space-1)",
        padding: "var(--bn-space-3) var(--bn-space-5)",
        borderRadius: "var(--bn-radius-chip)",
        background: bookable ? "var(--bn-pay-50)" : "var(--bn-hold-50)",
        color: bookable ? "var(--bn-pay-700)" : "var(--bn-hold-700)",
        fontSize: "var(--bn-text-body-sm-size)",
        minWidth: 150,
      }}
    >
      <span style={{ fontFamily: "var(--bn-font-mono)", fontWeight: 600 }}>
        {bookable ? `${money(service.deposit_amount)} deposit` : "No deposit"}
      </span>
      <span style={{ fontSize: "var(--bn-text-micro-size)" }}>
        {bookable ? "Bookable online" : "Staff and walk-ins only"}
      </span>
    </span>
  );
}

function ServiceRowEditor({
  initial,
  title,
  onSubmit,
  onCancel,
  onRetire,
}: {
  initial: Draft;
  title: string;
  onSubmit: (draft: Draft, done: () => void) => void;
  onCancel: () => void;
  onRetire?: () => void;
}) {
  const [draft, setDraft] = useState(initial);
  const [saving, setSaving] = useState(false);

  const set = (patch: Partial<Draft>) => setDraft((prev) => ({ ...prev, ...patch }));
  const price = Number(draft.price || 0);
  const ready = draft.name.trim() && draft.duration_minutes && draft.price;

  return (
    <div
      style={{
        border: "1.5px solid var(--bn-accent)",
        borderRadius: "var(--bn-radius-card)",
        padding: "var(--bn-space-7)",
        display: "grid",
        gap: "var(--bn-space-6)",
        background: "var(--bn-surface)",
      }}
    >
      <strong style={{ fontFamily: "var(--bn-font-display)" }}>{title}</strong>

      <Field label="Name" hint="What a client reads. Be specific — length and size matter to them.">
        <TextInput
          value={draft.name}
          onChange={(name) => set({ name })}
          placeholder="Knotless braids, medium, waist length"
        />
      </Field>

      <Grid min={200}>
        <Field label="How long" hint="Chair time, including the wash.">
          <NumberInput
            value={draft.duration_minutes}
            onChange={(duration_minutes) => set({ duration_minutes })}
            suffix="min"
          />
        </Field>
        <Field label="Price">
          <NumberInput value={draft.price} onChange={(p) => set({ price: p })} prefix="KES" />
        </Field>
      </Grid>

      <Grid min={200}>
        <Field label="Deposit">
          <Select
            value={draft.deposit_mode}
            onChange={(mode) =>
              set({
                deposit_mode: mode as Draft["deposit_mode"],
                // Switching modes carries a sensible starting value rather
                // than the previous mode's number, which would read as 25
                // shillings where 25 per cent was meant.
                deposit_value: mode === "percent" ? "25" : mode === "flat" ? "" : "",
              })
            }
            options={MODES}
          />
        </Field>
        {draft.deposit_mode !== "none" ? (
          <Field label={draft.deposit_mode === "percent" ? "Percentage" : "Amount"}>
            <NumberInput
              value={draft.deposit_value}
              onChange={(deposit_value) => set({ deposit_value })}
              prefix={draft.deposit_mode === "flat" ? "KES" : undefined}
              suffix={draft.deposit_mode === "percent" ? "%" : undefined}
            />
          </Field>
        ) : null}
      </Grid>

      <DepositPreview draft={draft} price={price} />

      <div style={{ display: "flex", gap: "var(--bn-space-6)", flexWrap: "wrap" }}>
        <Button
          onClick={() => {
            setSaving(true);
            onSubmit(draft, () => setSaving(false));
          }}
          disabled={!ready || saving}
          disabledReason={!ready ? "Name, length and price" : undefined}
          style={{ width: "auto", minWidth: 160 }}
        >
          {saving ? "Saving…" : "Save"}
        </Button>
        <Button variant="secondary" onClick={onCancel} style={{ width: "auto", minWidth: 120 }}>
          Cancel
        </Button>
        {onRetire ? (
          <Button
            variant="destructive"
            onClick={onRetire}
            style={{ width: "auto", minWidth: 120, marginLeft: "auto" }}
          >
            Retire
          </Button>
        ) : null}
      </div>
      {onRetire ? (
        <Note>
          Retiring hides a service from new bookings. Past appointments keep it, so your revenue
          figures do not change.
        </Note>
      ) : null}
    </div>
  );
}

/**
 * The design's live line — "29 % of KES 3,500 · balance KES 2,500 at the shop".
 *
 * An estimate, and it says so, because the authoritative figure is
 * `shops/money.py`'s and only exists once the row is saved: the shop's own
 * minimum floors it, and the price caps it. Showing an exact-looking number
 * that the server then rounds differently is worse than showing an
 * approximate one that admits it.
 */
function DepositPreview({ draft, price }: { draft: Draft; price: number }) {
  if (draft.deposit_mode === "none") {
    return (
      <p
        style={{
          margin: 0,
          padding: "var(--bn-space-6)",
          borderRadius: "var(--bn-radius-md)",
          background: "var(--bn-hold-50)",
          color: "var(--bn-hold-700)",
          textWrap: "pretty",
        }}
      >
        With no deposit this cannot be booked online. Staff can still book it and record it as a
        walk-in. The M-Pesa prompt is what verifies a client&apos;s number, so without one an
        unverified number would hold the chair for free.
      </p>
    );
  }

  const value = Number(draft.deposit_value || 0);
  if (!price || !value) return null;
  const estimate =
    draft.deposit_mode === "percent" ? Math.round((price * value) / 100) : Math.min(value, price);

  return (
    <p
      style={{
        margin: 0,
        padding: "var(--bn-space-6)",
        borderRadius: "var(--bn-radius-md)",
        background: "var(--bn-canvas)",
        color: "var(--bn-ink-70)",
      }}
    >
      About{" "}
      <strong style={{ fontFamily: "var(--bn-font-mono)", color: "var(--bn-ink)" }}>
        {money(estimate)}
      </strong>{" "}
      up front, {money(Math.max(0, price - estimate))} at the shop. The exact figure is set when
      you save, and never falls below your shop minimum.
    </p>
  );
}
