"use client";

/**
 * The shop itself: what a client reads, and the numbers the engine runs on.
 *
 * Two panels, deliberately far apart in weight. The first is the booking
 * page's content — name, address, the link. The second is scheduling
 * behaviour, which every shop can ignore: the defaults in `shops/models.py`
 * are the design's, they are correct for a salon, and an owner who opens this
 * screen on day one should not have to form an opinion about a slot interval.
 *
 * ## The slug is the one field that cannot be quietly fixed later
 *
 * It is the booking address — the thing that goes in a WhatsApp broadcast and
 * an Instagram bio. It is also globally unique across every tenant, because it
 * is a hostname (`shops/serializers.py` does the only genuine cross-tenant
 * read in the product to check it). So it is checked as the owner types, with
 * the address shown in full underneath, and a taken name comes back with a
 * suggestion rather than being silently suffixed.
 *
 * Once a shop exists the field is still editable, but changing it breaks every
 * link already sent — so it says so, which is the whole of the protection it
 * needs.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api } from "../../lib/api";
import { firstError } from "../../lib/auth";
import { Button, ErrorPanel, Field, Grid, NumberInput, Note, Section, TextInput } from "./primitives";

export type Shop = {
  id: string;
  name: string;
  slug: string;
  address: string;
  area: string;
  phone: string;
  directions_url: string;
  buffer_minutes: number;
  slot_interval_minutes: number;
  min_lead_minutes: number;
  booking_horizon_days: number;
  hold_ttl_minutes: number;
  refund_window_hours: number;
  deposit_credit_days: number;
  min_deposit_amount: number;
};

type SlugState = {
  slug: string;
  available: boolean;
  url?: string;
  reason?: string;
  suggestion?: string;
};

/** The nine digits after `+254`, matching `components/auth/fields.tsx`. */
function localPhone(raw: string): string {
  const digits = raw.replace(/\D/g, "");
  if (digits.startsWith("254")) return digits.slice(3, 12);
  if (digits.startsWith("0")) return digits.slice(1, 10);
  return digits.slice(0, 9);
}

/** The scheduling knobs, with the sentence that says what each one costs. */
const KNOBS: {
  key: keyof Shop;
  label: string;
  hint: string;
  suffix: string;
}[] = [
  {
    key: "buffer_minutes",
    label: "Gap between bookings",
    hint: "Sweeping up, washing brushes, the client actually leaving.",
    suffix: "min",
  },
  {
    key: "slot_interval_minutes",
    label: "Offer times every",
    hint: "Smaller means more times on the page and more of them awkward.",
    suffix: "min",
  },
  {
    key: "min_lead_minutes",
    label: "Earliest booking",
    hint: "How far ahead a client must book. Stops someone booking a slot as they walk in.",
    suffix: "min",
  },
  {
    key: "booking_horizon_days",
    label: "Book up to",
    hint: "How far into the future the page will go.",
    suffix: "days",
  },
  {
    key: "hold_ttl_minutes",
    label: "Hold an unpaid slot for",
    hint: "The M-Pesa window. The client sees this counting down while they enter their PIN.",
    suffix: "min",
  },
  {
    key: "min_deposit_amount",
    label: "Smallest deposit",
    hint: "A deposit below this is rounded up to it. Under about KES 50 the prompt costs more than it collects.",
    suffix: "KES",
  },
];

export function ShopForm({
  orgId,
  shop,
  onSaved,
}: {
  orgId: string;
  /** Absent when this is the org's first shop — the same form creates it. */
  shop: Shop | null;
  onSaved: (shop: Shop) => void;
}) {
  const [name, setName] = useState(shop?.name ?? "");
  const [slug, setSlug] = useState(shop?.slug ?? "");
  const [slugTouched, setSlugTouched] = useState(Boolean(shop));
  const [address, setAddress] = useState(shop?.address ?? "");
  const [area, setArea] = useState(shop?.area ?? "");
  const [phone, setPhone] = useState(localPhone(shop?.phone ?? ""));
  const [directions, setDirections] = useState(shop?.directions_url ?? "");
  const [knobs, setKnobs] = useState(() =>
    Object.fromEntries(KNOBS.map((knob) => [knob.key, String(shop?.[knob.key] ?? "")]))
  );
  const [slugState, setSlugState] = useState<SlugState | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  // The address is derived from the name until the owner edits it themselves.
  // Typing "Mint Braids Kilimani" and getting the matching link for free is
  // the common case; the moment they touch the field it is theirs.
  const effectiveSlug = slugTouched
    ? slug
    : name
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-|-$/g, "")
        .slice(0, 63);

  const checkSeq = useRef(0);

  const checkSlug = useCallback(
    (candidate: string) => {
      if (!candidate) {
        setSlugState(null);
        return;
      }
      // Every check is numbered and only the newest is allowed to write. A
      // slow response for "mint" must not overwrite the answer for
      // "mint-braids" typed after it and answered first.
      const seq = (checkSeq.current += 1);
      api
        .get(`/api/v1/orgs/${orgId}/shops/check-slug/?slug=${encodeURIComponent(candidate)}`)
        .then((data) => {
          if (seq === checkSeq.current) setSlugState(data);
        })
        .catch(() => {
          if (seq === checkSeq.current) setSlugState(null);
        });
    },
    [orgId]
  );

  useEffect(() => {
    // Unchanged from what is already saved is not worth a request, and would
    // report the shop's own address as taken.
    if (shop && effectiveSlug === shop.slug) {
      setSlugState(null);
      return;
    }
    const timer = setTimeout(() => checkSlug(effectiveSlug), 400);
    return () => clearTimeout(timer);
  }, [effectiveSlug, checkSlug, shop]);

  function save() {
    setSaving(true);
    setError("");
    const payload: Record<string, unknown> = {
      name,
      slug: effectiveSlug,
      address,
      area,
      phone: phone ? `+254${phone}` : "",
      directions_url: directions,
    };
    for (const knob of KNOBS) {
      const raw = knobs[knob.key];
      if (raw !== "") payload[knob.key] = Number(raw);
    }

    const request = shop
      ? api.patch(`/api/v1/orgs/${orgId}/shops/${shop.id}/`, payload)
      : api.post(`/api/v1/orgs/${orgId}/shops/`, payload);

    request
      .then((saved) => onSaved(saved))
      .catch((caught) => {
        // The server's own sentence, not a generic one. The slug error in
        // particular is a paragraph of useful advice with a suggestion in it,
        // and replacing it with "Could not save" throws that away.
        setError(caught instanceof ApiError ? firstError(caught.body, "Could not save.") : "Could not save.");
      })
      .finally(() => setSaving(false));
  }

  const blocked = !name.trim() || !effectiveSlug || slugState?.available === false;

  return (
    <>
      <Section
        id="setup-shop"
        title={shop ? "Shop details" : "Your first shop"}
        intro={
          shop
            ? "What a client reads at the top of your booking page."
            : "One shop to start with. You can add branches later, and clients carry one history across all of them."
        }
      >
        <Grid>
          <Field label="Shop name" hint="Clients see this, and so does the confirmation SMS.">
            <TextInput value={name} onChange={setName} placeholder="Mint Braids Kilimani" />
          </Field>
          <Field label="Area" hint="The neighbourhood, e.g. Wood Ave.">
            <TextInput value={area} onChange={setArea} placeholder="Kilimani" />
          </Field>
        </Grid>

        <Field
          label="Booking address"
          hint={
            shop
              ? "Changing this breaks every link you have already sent."
              : "This is the link you paste into WhatsApp. It has to be unique across all of BookNasi."
          }
          error={slugState && !slugState.available ? slugState.reason : undefined}
        >
          <TextInput
            value={effectiveSlug}
            mono
            onChange={(value) => {
              setSlugTouched(true);
              setSlug(value.toLowerCase().replace(/[^a-z0-9-]/g, ""));
            }}
            placeholder="mint-braids-kilimani"
          />
        </Field>
        <SlugLine state={slugState} slug={effectiveSlug} onTake={(next) => {
          setSlugTouched(true);
          setSlug(next);
        }} />

        <Grid>
          <Field label="Address" hint="Street and building, for the directions link.">
            <TextInput value={address} onChange={setAddress} placeholder="Wood Ave, 2nd floor" />
          </Field>
          <Field label="Shop phone" hint="Shown to a client who needs to call you.">
            <NumberInput value={phone} onChange={(v) => setPhone(v.slice(0, 9))} prefix="+254" placeholder="712345678" />
          </Field>
        </Grid>

        <Field
          label="Directions link"
          hint="A Google Maps or Apple Maps link. The client's Directions button opens it."
        >
          <TextInput
            value={directions}
            onChange={setDirections}
            type="url"
            placeholder="https://maps.app.goo.gl/…"
          />
        </Field>

        <ErrorPanel>{error}</ErrorPanel>

        <div style={{ display: "flex", gap: "var(--bn-space-6)", flexWrap: "wrap" }}>
          <Button
            onClick={save}
            disabled={blocked || saving}
            disabledReason={
              slugState?.available === false
                ? "That booking address is taken"
                : !name.trim()
                  ? "Give the shop a name"
                  : undefined
            }
            style={{ width: "auto", minWidth: 200 }}
          >
            {saving ? "Saving…" : shop ? "Save changes" : "Create shop"}
          </Button>
        </div>
      </Section>

      {shop ? (
        <Section
          title="Scheduling"
          intro="Sensible defaults for a salon. Most shops never change these."
        >
          <Grid min={260}>
            {KNOBS.map((knob) => (
              <Field key={knob.key} label={knob.label} hint={knob.hint}>
                <NumberInput
                  value={knobs[knob.key]}
                  onChange={(value) => setKnobs((prev) => ({ ...prev, [knob.key]: value }))}
                  suffix={knob.suffix}
                />
              </Field>
            ))}
          </Grid>
          <Note>
            The refund window is set with your cancellation terms, under Services — it changes the
            sentence clients agree to before paying, so it lives next to the wording.
          </Note>
          <div>
            <Button onClick={save} disabled={saving} style={{ width: "auto", minWidth: 200 }}>
              {saving ? "Saving…" : "Save changes"}
            </Button>
          </div>
        </Section>
      ) : null}
    </>
  );
}

/** The address in full, and a one-tap way to take the suggestion. */
function SlugLine({
  state,
  slug,
  onTake,
}: {
  state: SlugState | null;
  slug: string;
  onTake: (slug: string) => void;
}) {
  if (!slug) return null;
  const url = state?.url ?? `https://${slug}.booknasi.co.ke`;
  const taken = state?.available === false;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--bn-space-6)",
        flexWrap: "wrap",
        padding: "var(--bn-space-5) var(--bn-space-6)",
        borderRadius: "var(--bn-radius-md)",
        background: taken ? "var(--bn-fail-50)" : "var(--bn-canvas)",
      }}
    >
      <span
        style={{
          fontFamily: "var(--bn-font-mono)",
          color: taken ? "var(--bn-fail-700)" : "var(--bn-ink)",
          wordBreak: "break-all",
        }}
      >
        {url.replace(/^https:\/\//, "")}
      </span>
      {state?.suggestion ? (
        <button
          type="button"
          onClick={() => onTake(state.suggestion as string)}
          style={{
            minHeight: "var(--bn-target-control)",
            padding: "0 var(--bn-space-6)",
            borderRadius: "var(--bn-radius-md)",
            border: "1.5px solid var(--bn-border)",
            background: "var(--bn-surface)",
            color: "var(--bn-ink)",
            font: "inherit",
            cursor: "pointer",
          }}
        >
          Use {state.suggestion}
        </button>
      ) : null}
    </div>
  );
}

