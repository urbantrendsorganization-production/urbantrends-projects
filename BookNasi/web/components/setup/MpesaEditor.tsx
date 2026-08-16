"use client";

/**
 * Where this shop's deposits land.
 *
 * The design's onboarding step 3, and the one step slice 12 could not build:
 * `MPESA_SHORTCODE` was environment-level, so every shop on a deployment
 * collected into the same till. Slice 13 moved it onto the shop, and this is
 * the screen that sets it.
 *
 * ## Owner only, and the screen says why
 *
 * `/api/v1/orgs/…/shops/…/mpesa/` is the only endpoint in the product that a
 * manager cannot reach. A manager already sets prices and deposit rules, so
 * they decide how much is taken; where it lands is a different act and a quiet
 * one, because the number comes back masked and nobody else on the account
 * could see it had changed. The setup page therefore hides this tab from a
 * manager rather than showing them a 403 — a tab that only ever fails is worse
 * than no tab.
 *
 * ## Secrets are write-only, and the empty box means "leave it alone"
 *
 * The three Daraja secrets never come back from the API. What comes back is
 * eight bullets and the last four characters, which answers the only question
 * an owner has about a secret they cannot read: *is the thing I typed still
 * the thing that is stored*. So each input starts empty with the mask as its
 * placeholder, and sending nothing leaves the stored value untouched — an
 * owner correcting a mistyped paybill number does not have to re-enter a
 * passkey to do it. Clearing one is `Disconnect`, which is a named action
 * rather than a PATCH of blanks, because a stale form can send blanks by
 * accident and the result is a shop that silently stops taking deposits.
 *
 * ## Buttons, not radios
 *
 * Same reason `Toggle` is not a checkbox (see `primitives.tsx`): CLAUDE.md
 * §10's floor is about a target somebody aims at one-handed, and a 16 px radio
 * inside a 52 px label still reads and aims like a 16 px radio.
 */

import { useState } from "react";

import { ApiError, api } from "../../lib/api";
import { firstError } from "../../lib/auth";
import {
  Button,
  ErrorPanel,
  Field,
  Grid,
  Note,
  Section,
  TextInput,
  Tick,
} from "./primitives";

const PAYBILL = "CustomerPayBillOnline";
const TILL = "CustomerBuyGoodsOnline";

export type Mpesa = {
  collects_via: "own" | "platform";
  mpesa_shortcode: string;
  mpesa_till_number: string;
  mpesa_transaction_type: string;
  consumer_key_masked: string;
  consumer_secret_masked: string;
  passkey_masked: string;
  is_connected: boolean;
  platform_available: boolean;
  can_store_credentials: boolean;
};

type Draft = {
  shortcode: string;
  till: string;
  type: string;
  consumerKey: string;
  consumerSecret: string;
  passkey: string;
};

function draftFrom(mpesa: Mpesa): Draft {
  return {
    shortcode: mpesa.mpesa_shortcode,
    till: mpesa.mpesa_till_number,
    // Blank on the server means paybill, matching the deployment default. The
    // form resolves it so the two options are never both unselected.
    type: mpesa.mpesa_transaction_type || PAYBILL,
    consumerKey: "",
    consumerSecret: "",
    passkey: "",
  };
}

export function MpesaEditor({
  orgId,
  shopId,
  mpesa,
  onChanged,
}: {
  orgId: string;
  shopId: string;
  mpesa: Mpesa;
  onChanged: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => draftFrom(mpesa));
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const own = mpesa.collects_via === "own";
  const isTill = draft.type === TILL;

  function set<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
    setSaved(false);
  }

  function send(body: Record<string, unknown>) {
    setSaving(true);
    setError("");
    api
      .patch(`/api/v1/orgs/${orgId}/shops/${shopId}/mpesa/`, body)
      .then(() => {
        // The secrets are cleared from the form once they are stored. Leaving
        // them in the boxes would put three live credentials on a shared salon
        // screen for as long as the tab stays open, to no purpose — they are
        // not readable back, so nothing is lost by dropping them.
        setDraft((current) => ({
          ...current,
          consumerKey: "",
          consumerSecret: "",
          passkey: "",
        }));
        setSaved(true);
        onChanged();
      })
      .catch((caught) =>
        setError(
          caught instanceof ApiError ? firstError(caught.body, "Could not save.") : "Could not save."
        )
      )
      .finally(() => setSaving(false));
  }

  function chooseOwn() {
    send({ collects_via: "own" });
  }

  function choosePlatform() {
    send({ collects_via: "platform" });
  }

  function save() {
    const body: Record<string, unknown> = {
      collects_via: "own",
      mpesa_shortcode: draft.shortcode.trim(),
      mpesa_transaction_type: draft.type,
      mpesa_till_number: isTill ? draft.till.trim() : "",
    };
    // Only what was typed. An absent field means "keep what is stored"; an
    // empty string would mean "clear it", and sending three of those on every
    // save is how an owner editing a paybill number disconnects their shop.
    if (draft.consumerKey) body.consumer_key = draft.consumerKey.trim();
    if (draft.consumerSecret) body.consumer_secret = draft.consumerSecret.trim();
    if (draft.passkey) body.passkey = draft.passkey.trim();
    send(body);
  }

  function disconnect() {
    setSaving(true);
    setError("");
    api
      .post(`/api/v1/orgs/${orgId}/shops/${shopId}/mpesa/disconnect/`, {})
      .then(() => {
        setDraft({
          shortcode: "",
          till: "",
          type: PAYBILL,
          consumerKey: "",
          consumerSecret: "",
          passkey: "",
        });
        setSaved(false);
        onChanged();
      })
      .catch(() => setError("Could not disconnect."))
      .finally(() => setSaving(false));
  }

  return (
    <>
      <Section
        id="setup-mpesa"
        title="Where deposits land"
        intro="Deposits go straight to your own M-Pesa. BookNasi never holds your clients' money."
      >
        <ErrorPanel>{error}</ErrorPanel>

        <Status mpesa={mpesa} />

        {mpesa.platform_available ? (
          <div style={{ display: "grid", gap: "var(--bn-space-4)" }}>
            <Choice
              selected={own}
              onSelect={chooseOwn}
              disabled={saving}
              title="Your own M-Pesa"
              detail="Your Paybill or Till. Deposits arrive in your account the moment a client pays."
            />
            <Choice
              selected={!own}
              onSelect={choosePlatform}
              disabled={saving}
              title="BookNasi's account"
              detail="We collect on your behalf and settle separately. Ask support before choosing this."
            />
          </div>
        ) : null}

        {own ? (
          <>
            <div style={{ display: "grid", gap: "var(--bn-space-4)" }}>
              <Choice
                selected={!isTill}
                onSelect={() => set("type", PAYBILL)}
                disabled={saving}
                title="Paybill"
                detail="Clients pay to a paybill number with an account reference."
              />
              <Choice
                selected={isTill}
                onSelect={() => set("type", TILL)}
                disabled={saving}
                title="Till (Buy Goods)"
                detail="Clients pay to a till number. You will need both the store number and the till number."
              />
            </div>

            <Grid>
              <Field
                label={isTill ? "Store number" : "Paybill number"}
                hint={
                  isTill
                    ? "Safaricom calls this the head office number. It is not the till number."
                    : "Digits only."
                }
              >
                <TextInput
                  mono
                  value={draft.shortcode}
                  onChange={(value) => set("shortcode", value)}
                  placeholder="123456"
                />
              </Field>

              {isTill ? (
                <Field
                  label="Till number"
                  hint="The number clients actually pay. Different from the store number above."
                >
                  <TextInput
                    mono
                    value={draft.till}
                    onChange={(value) => set("till", value)}
                    placeholder="654321"
                  />
                </Field>
              ) : null}
            </Grid>

            <Secrets draft={draft} mpesa={mpesa} set={set} />

            <div
              style={{
                display: "flex",
                gap: "var(--bn-space-6)",
                flexWrap: "wrap",
                alignItems: "center",
              }}
            >
              <Button
                onClick={save}
                disabled={saving || !draft.shortcode.trim() || !mpesa.can_store_credentials}
                disabledReason={
                  !mpesa.can_store_credentials
                    ? "This deployment cannot store credentials"
                    : !draft.shortcode.trim()
                      ? "Add your number first"
                      : undefined
                }
                style={{ width: "auto" }}
              >
                {saving ? "Saving…" : "Save"}
              </Button>
              {saved ? <Note>Saved.</Note> : null}
              {mpesa.mpesa_shortcode ? (
                <Button
                  variant="quiet"
                  onClick={disconnect}
                  disabled={saving}
                  style={{ width: "auto", padding: "0 var(--bn-space-6)" }}
                >
                  Disconnect
                </Button>
              ) : null}
            </div>

            <Note>
              Your keys come from the Safaricom Daraja portal, under your app&rsquo;s credentials.
              We store them encrypted and never show them again — you will see only the last four
              characters after saving.
            </Note>
          </>
        ) : null}
      </Section>

      {own ? <WhereToFindThem /> : null}
    </>
  );
}

/**
 * The one-line answer to "is this on?".
 *
 * Leads with the consequence rather than the configuration, the same way the
 * services editor leads with "Bookable online" rather than the deposit mode: an
 * owner opening this tab wants to know whether clients can pay, not which
 * fields are populated.
 */
function Status({ mpesa }: { mpesa: Mpesa }) {
  const good = mpesa.is_connected;
  return (
    <p
      style={{
        margin: 0,
        padding: "var(--bn-space-5) var(--bn-space-6)",
        borderRadius: "var(--bn-radius-md)",
        border: "1px solid var(--bn-line)",
        background: good ? "var(--bn-ok-50)" : "var(--bn-canvas)",
        color: good ? "var(--bn-ok-700)" : "var(--bn-ink)",
      }}
    >
      {good
        ? mpesa.collects_via === "platform"
          ? "Deposits are being collected into the BookNasi account."
          : mpesa.mpesa_transaction_type === TILL
            ? `Connected. Deposits go to till ${mpesa.mpesa_till_number}.`
            : `Connected. Deposits go to paybill ${mpesa.mpesa_shortcode}.`
        : "Not connected yet, so this shop cannot be booked online. Nothing has been collected into the wrong account — a shop is never quietly switched to somebody else's till."}
    </p>
  );
}

/** A 52 px selectable row. See the module note on why this is not a radio. */
function Choice({
  selected,
  onSelect,
  disabled,
  title,
  detail,
}: {
  selected: boolean;
  onSelect: () => void;
  disabled?: boolean;
  title: string;
  detail: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      disabled={disabled}
      onClick={onSelect}
      style={{
        minHeight: 52,
        width: "100%",
        display: "flex",
        alignItems: "center",
        gap: "var(--bn-space-5)",
        textAlign: "left",
        padding: "var(--bn-space-4) var(--bn-space-6)",
        borderRadius: "var(--bn-radius-md)",
        border: selected ? "1.5px solid var(--bn-accent)" : "1.5px solid var(--bn-border)",
        background: selected ? "var(--bn-accent-50)" : "var(--bn-surface)",
        color: "var(--bn-ink)",
        cursor: disabled ? "default" : "pointer",
        font: "inherit",
      }}
    >
      <Tick checked={selected} />
      <span style={{ display: "grid", gap: "var(--bn-space-2)" }}>
        <span style={{ fontWeight: 600 }}>{title}</span>
        <span style={{ color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
          {detail}
        </span>
      </span>
    </button>
  );
}

/**
 * The three Daraja secrets.
 *
 * Each box is empty and carries the stored value's mask as its placeholder, so
 * "already set" and "not set yet" look different without either being readable.
 * `type="password"` is not about hiding it from the owner — they are pasting it
 * — but a salon laptop faces a counter, and a passkey sitting visible in a form
 * is one anybody standing there can photograph.
 */
function Secrets({
  draft,
  mpesa,
  set,
}: {
  draft: Draft;
  mpesa: Mpesa;
  set: <K extends keyof Draft>(key: K, value: Draft[K]) => void;
}) {
  const rows: { key: keyof Draft; label: string; masked: string }[] = [
    { key: "consumerKey", label: "Consumer key", masked: mpesa.consumer_key_masked },
    { key: "consumerSecret", label: "Consumer secret", masked: mpesa.consumer_secret_masked },
    { key: "passkey", label: "Passkey", masked: mpesa.passkey_masked },
  ];

  return (
    <Grid min={260}>
      {rows.map((row) => (
        <Field
          key={row.key}
          label={row.label}
          hint={
            row.masked === "unreadable"
              ? "Stored, but this deployment can no longer read it. Enter it again."
              : row.masked
                ? `Stored as ${row.masked}. Leave blank to keep it.`
                : "Not set yet."
          }
        >
          <TextInput
            type="password"
            mono
            value={draft[row.key] as string}
            onChange={(value) => set(row.key, value)}
            placeholder={row.masked || ""}
          />
        </Field>
      ))}
    </Grid>
  );
}

function WhereToFindThem() {
  return (
    <Section
      title="Getting your Daraja keys"
      intro="Once, from Safaricom. Ten minutes, and you will not need to do it again."
    >
      <ol
        style={{
          margin: 0,
          paddingLeft: "1.2em",
          display: "grid",
          gap: "var(--bn-space-5)",
          color: "var(--bn-ink)",
        }}
      >
        <li>
          Sign in at <span style={{ fontFamily: "var(--bn-font-mono)" }}>developer.safaricom.co.ke</span>{" "}
          with the number your Paybill or Till is registered to.
        </li>
        <li>Create an app, and tick Lipa na M-Pesa Online. That gives you the consumer key and secret.</li>
        <li>
          Under Lipa na M-Pesa Online, request Go Live for your Paybill or Till. Safaricom sends the
          passkey once approved.
        </li>
        <li>Paste all three above and press Save.</li>
      </ol>
      <Note>
        Approval can take a few working days. Until it comes through, staff can still book and record
        walk-ins — only online booking needs the deposit.
      </Note>
    </Section>
  );
}
