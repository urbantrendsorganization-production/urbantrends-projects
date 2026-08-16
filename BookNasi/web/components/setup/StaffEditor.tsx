"use client";

/**
 * The people, their days, and what each of them actually does.
 *
 * Three things live here because they are three columns of one row in the
 * owner's head — "Grace, Tuesday to Saturday, braids and cornrows" — and
 * splitting them across screens is how a stylist ends up rostered with no
 * services ticked, which is the single most common way a fully configured
 * shop offers nothing.
 *
 * ## A chair and a login are different things
 *
 * `Staff` is a bookable row at a shop; `Membership` is a person who can sign
 * in; `StaffInvite` is an SMS that turns the second into a fact. CLAUDE.md §12
 * keeps them apart deliberately — per-person logins are what make the owner
 * dashboard's revenue attribution mean anything, and a shared login would
 * destroy it.
 *
 * The consequence for this screen is that **adding a chair does not send
 * anything**. An owner can set up their whole shop on a Sunday evening with
 * five chairs and no invites, and the calendar works; the invites are what let
 * those five people see their own day. So the two actions are adjacent and
 * separate, and the row says which state it is in — the design's
 * `Invited 3 Aug · hasn't signed in yet`.
 *
 * ## Skills are a tick, and the duration override is behind it
 *
 * CLAUDE.md §3: a senior stylist does in 30 minutes what a junior takes 50
 * for, and if the schedule cannot express that the calendar lies. The tick
 * creates the `StaffService` link; the number beside it is
 * `duration_override_minutes`, blank meaning "the service's own time". Blank
 * is not zero and the field says so, because a 0 there would be a stylist who
 * takes no time at all.
 */

import { spellDuration } from "@booknasi/booking-core";
import { useState } from "react";

import { ApiError, api } from "../../lib/api";
import { firstError } from "../../lib/auth";
import type { Service } from "./ServicesEditor";
import {
  Button,
  Empty,
  ErrorPanel,
  Field,
  Grid,
  NumberInput,
  Note,
  Section,
  TextInput,
  Toggle,
} from "./primitives";

export type Staff = {
  id: string;
  display_name: string;
  is_bookable: boolean;
  is_active: boolean;
  has_signed_in: boolean;
  membership: string | null;
};

export type WorkingHours = {
  id: string;
  weekday: number;
  starts_at: string;
  ends_at: string;
};

export type StaffService = {
  id: string;
  service: string;
  duration_override_minutes: number | null;
  is_offered: boolean;
  effective_duration_minutes: number | null;
};

export type Invite = {
  id: string;
  phone: string;
  role: string;
  status: "pending" | "accepted" | "revoked" | "expired";
  created_at: string;
};

/** Per-staff detail, loaded when a row is opened rather than for the whole
 *  shop up front: a shop with twelve stylists would otherwise cost
 *  twenty-four requests to draw a list nobody has expanded. */
export type StaffDetail = { hours: WorkingHours[]; skills: StaffService[] };

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const DEFAULT_START = "09:00";
const DEFAULT_END = "18:00";

function hhmm(value: string): string {
  return value.slice(0, 5);
}

export function StaffEditor({
  orgId,
  shopId,
  staff,
  services,
  invites,
  details,
  openStaffId,
  onOpenStaff,
  onChanged,
}: {
  orgId: string;
  shopId: string;
  staff: Staff[];
  services: Service[];
  invites: Invite[];
  details: Record<string, StaffDetail>;
  openStaffId: string | null;
  onOpenStaff: (id: string | null) => void;
  onChanged: () => void;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);

  function addStaff() {
    setAdding(true);
    setError("");
    api
      .post(`/api/v1/orgs/${orgId}/shops/${shopId}/staff/`, { display_name: name })
      .then((created) => {
        setName("");
        onChanged();
        // Straight into their detail: a chair with no days and no services is
        // not finished, and the next two things to do are inside this panel.
        onOpenStaff(created.id);
      })
      .catch((caught) =>
        setError(caught instanceof ApiError ? firstError(caught.body, "Could not save.") : "Could not add.")
      )
      .finally(() => setAdding(false));
  }

  return (
    <>
      <Section
        id="setup-staff"
        title="Chairs"
        intro="One row per person who takes bookings. Their days and services are inside each row."
      >
        <ErrorPanel>{error}</ErrorPanel>

        {staff.length === 0 ? (
          <Empty title="No chairs yet">
            <Note>
              Add yourself first if you take clients. Every booking belongs to one person&apos;s
              chair, including your own.
            </Note>
          </Empty>
        ) : null}

        <div style={{ display: "grid", gap: "var(--bn-space-5)" }}>
          {staff.map((person) => (
            <StaffRow
              key={person.id}
              orgId={orgId}
              shopId={shopId}
              person={person}
              services={services}
              detail={details[person.id]}
              open={openStaffId === person.id}
              onToggle={() => onOpenStaff(openStaffId === person.id ? null : person.id)}
              onChanged={onChanged}
            />
          ))}
        </div>

        <div style={{ display: "flex", gap: "var(--bn-space-6)", alignItems: "end", flexWrap: "wrap" }}>
          <Field label="Add a chair" hint="The name clients see, e.g. Wanjiku.">
            <TextInput value={name} onChange={setName} placeholder="Wanjiku" />
          </Field>
          <Button
            onClick={addStaff}
            disabled={!name.trim() || adding}
            disabledReason={!name.trim() ? "Type a name" : undefined}
            style={{ width: "auto", minWidth: 160 }}
          >
            {adding ? "Adding…" : "Add"}
          </Button>
        </div>
      </Section>

      <InvitesPanel orgId={orgId} invites={invites} onChanged={onChanged} />
    </>
  );
}

function StaffRow({
  orgId,
  shopId,
  person,
  services,
  detail,
  open,
  onToggle,
  onChanged,
}: {
  orgId: string;
  shopId: string;
  person: Staff;
  services: Service[];
  detail: StaffDetail | undefined;
  open: boolean;
  onToggle: () => void;
  onChanged: () => void;
}) {
  const [error, setError] = useState("");

  const rosteredDays = detail?.hours.length ?? null;
  const skillCount = detail?.skills.filter((link) => link.is_offered).length ?? null;

  return (
    <div
      style={{
        border: open ? "1.5px solid var(--bn-accent)" : "1px solid var(--bn-line)",
        borderRadius: "var(--bn-radius-card)",
        background: person.is_active ? "var(--bn-surface)" : "var(--bn-canvas)",
        overflow: "hidden",
      }}
    >
      <button
        type="button"
        onClick={onToggle}
        style={{
          minHeight: "var(--bn-target-control)",
          width: "100%",
          display: "flex",
          alignItems: "center",
          gap: "var(--bn-space-6)",
          padding: "var(--bn-space-5) var(--bn-space-6)",
          background: "transparent",
          border: "none",
          cursor: "pointer",
          textAlign: "left",
          font: "inherit",
          color: "var(--bn-ink)",
          flexWrap: "wrap",
        }}
      >
        <span style={{ display: "grid", gap: "var(--bn-space-2)", flex: 1, minWidth: 160 }}>
          <span style={{ fontWeight: 600 }}>
            {person.display_name}
            {person.is_active ? "" : " · left"}
          </span>
          <span style={{ color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
            {/*
              The adoption line the design asks the staff list to double as.
              A chair with no login is not broken — it is a person the owner
              books on behalf of — so it reads as a fact, not a warning.
            */}
            {person.has_signed_in ? "Signed in" : "No login yet"}
            {rosteredDays === null
              ? ""
              : ` · ${rosteredDays} ${rosteredDays === 1 ? "day" : "days"} a week · ${skillCount} ${
                  skillCount === 1 ? "service" : "services"
                }`}
          </span>
        </span>
        <span style={{ color: "var(--bn-ink-45)" }}>{open ? "Close" : "Days and services"}</span>
      </button>

      {open ? (
        <div
          style={{
            borderTop: "1px solid var(--bn-line)",
            padding: "var(--bn-space-7)",
            display: "grid",
            gap: "var(--bn-space-8)",
          }}
        >
          <ErrorPanel>{error}</ErrorPanel>

          {detail ? (
            <>
              <Roster
                orgId={orgId}
                staffId={person.id}
                hours={detail.hours}
                onChanged={onChanged}
                onError={setError}
              />
              <Skills
                orgId={orgId}
                staffId={person.id}
                services={services}
                skills={detail.skills}
                onChanged={onChanged}
                onError={setError}
              />
              <Presence
                orgId={orgId}
                shopId={shopId}
                person={person}
                onChanged={onChanged}
                onError={setError}
              />
            </>
          ) : (
            <Note>Loading…</Note>
          )}
        </div>
      ) : null}
    </div>
  );
}

/** Which days this person works, and between what times. */
function Roster({
  orgId,
  staffId,
  hours,
  onChanged,
  onError,
}: {
  orgId: string;
  staffId: string;
  hours: WorkingHours[];
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  const byDay = new Map(hours.map((row) => [row.weekday, row]));

  function fail(caught: unknown) {
    onError(caught instanceof ApiError ? firstError(caught.body, "Could not save.") : "Could not save.");
  }

  function toggle(weekday: number) {
    const existing = byDay.get(weekday);
    if (existing) {
      api
        .del(`/api/v1/orgs/${orgId}/staff/${staffId}/working-hours/${existing.id}/`)
        .then(onChanged)
        .catch(fail);
      return;
    }
    const template = hours[0];
    api
      .post(`/api/v1/orgs/${orgId}/staff/${staffId}/working-hours/`, {
        weekday,
        starts_at: template ? hhmm(template.starts_at) : DEFAULT_START,
        ends_at: template ? hhmm(template.ends_at) : DEFAULT_END,
      })
      .then(onChanged)
      .catch(fail);
  }

  function setTime(row: WorkingHours, field: "starts_at" | "ends_at", value: string) {
    api
      .patch(`/api/v1/orgs/${orgId}/staff/${staffId}/working-hours/${row.id}/`, { [field]: value })
      .then(onChanged)
      .catch(fail);
  }

  return (
    <div style={{ display: "grid", gap: "var(--bn-space-5)" }}>
      <strong style={{ fontFamily: "var(--bn-font-display)" }}>Days worked</strong>
      <Note>
        Only days the shop is also open produce bookable times. A shift shorter than a service is
        not long enough to fit it.
      </Note>
      <div style={{ display: "grid", gap: "var(--bn-space-4)" }}>
        {DAYS.map((label, weekday) => {
          const row = byDay.get(weekday);
          return (
            <div
              key={label}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "var(--bn-space-6)",
                flexWrap: "wrap",
              }}
            >
              <span style={{ minWidth: 140 }}>
                <Toggle checked={Boolean(row)} onChange={() => toggle(weekday)} label={label} />
              </span>
              {row ? (
                <span style={{ display: "flex", alignItems: "center", gap: "var(--bn-space-5)" }}>
                  <TextInput
                    type="time"
                    mono
                    value={hhmm(row.starts_at)}
                    onChange={(value) => setTime(row, "starts_at", value)}
                  />
                  <span aria-hidden="true" style={{ color: "var(--bn-ink-45)" }}>
                    to
                  </span>
                  <TextInput
                    type="time"
                    mono
                    value={hhmm(row.ends_at)}
                    onChange={(value) => setTime(row, "ends_at", value)}
                  />
                </span>
              ) : (
                <span style={{ color: "var(--bn-ink-45)" }}>Off</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** What this person does, and how long they take over it. */
function Skills({
  orgId,
  staffId,
  services,
  skills,
  onChanged,
  onError,
}: {
  orgId: string;
  staffId: string;
  services: Service[];
  skills: StaffService[];
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  const byService = new Map(skills.map((link) => [link.service, link]));

  function fail(caught: unknown) {
    onError(caught instanceof ApiError ? firstError(caught.body, "Could not save.") : "Could not save.");
  }

  function toggle(serviceId: string) {
    const link = byService.get(serviceId);
    if (link) {
      api
        .del(`/api/v1/orgs/${orgId}/staff/${staffId}/services/${link.id}/`)
        .then(onChanged)
        .catch(fail);
      return;
    }
    api
      .post(`/api/v1/orgs/${orgId}/staff/${staffId}/services/`, { service: serviceId })
      .then(onChanged)
      .catch(fail);
  }

  function setOverride(link: StaffService, raw: string) {
    api
      .patch(`/api/v1/orgs/${orgId}/staff/${staffId}/services/${link.id}/`, {
        // Empty means "use the service's own time". `null` says that; `0`
        // would be a stylist who takes no time, which the model refuses.
        duration_override_minutes: raw === "" ? null : Number(raw),
      })
      .then(onChanged)
      .catch(fail);
  }

  const sellable = services.filter((service) => service.is_active);

  return (
    <div style={{ display: "grid", gap: "var(--bn-space-5)" }}>
      <strong style={{ fontFamily: "var(--bn-font-display)" }}>Services offered</strong>
      {sellable.length === 0 ? (
        <Note>Add a service first, then come back and tick who does it.</Note>
      ) : (
        <>
          <Note>
            Nothing is offered until it is ticked. Leave the time blank to use the service&apos;s
            own length, or set a different one for this person.
          </Note>
          <div style={{ display: "grid", gap: "var(--bn-space-4)" }}>
            {sellable.map((service) => {
              const link = byService.get(service.id);
              return (
                <div
                  key={service.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "var(--bn-space-6)",
                    flexWrap: "wrap",
                  }}
                >
                  <span style={{ flex: 1, minWidth: 200 }}>
                    <Toggle
                      checked={Boolean(link?.is_offered)}
                      onChange={() => toggle(service.id)}
                      label={service.name}
                      hint={`Normally ${spellDuration(service.duration_minutes)}`}
                    />
                  </span>
                  {link?.is_offered ? (
                    <span style={{ minWidth: 190 }}>
                      <Field label="Their time">
                        <NumberInput
                          value={
                            link.duration_override_minutes === null
                              ? ""
                              : String(link.duration_override_minutes)
                          }
                          onChange={(value) => setOverride(link, value)}
                          placeholder={String(service.duration_minutes)}
                          suffix="min"
                        />
                      </Field>
                    </span>
                  ) : null}
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

/** Bookable, and still here at all. */
function Presence({
  orgId,
  shopId,
  person,
  onChanged,
  onError,
}: {
  orgId: string;
  shopId: string;
  person: Staff;
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  function patch(payload: Record<string, unknown>) {
    api
      .patch(`/api/v1/orgs/${orgId}/shops/${shopId}/staff/${person.id}/`, payload)
      .then(onChanged)
      .catch((caught) =>
        onError(caught instanceof ApiError ? firstError(caught.body, "Could not save.") : "Could not save.")
      );
  }

  return (
    <div style={{ display: "grid", gap: "var(--bn-space-5)" }}>
      <strong style={{ fontFamily: "var(--bn-font-display)" }}>Availability</strong>
      <Grid min={260}>
        <Toggle
          checked={person.is_bookable}
          onChange={(is_bookable) => patch({ is_bookable })}
          label="Clients can pick this person"
          hint="Off for a manager who does not take appointments."
        />
        <Toggle
          checked={person.is_active}
          onChange={(is_active) => patch({ is_active })}
          label="Still works here"
          hint="Turning this off keeps their past bookings and revenue."
        />
      </Grid>
    </div>
  );
}

/**
 * Invites — the SMS that turns a chair into a person who can sign in.
 *
 * The token comes back on the response exactly once and is never returned
 * again (`orgs/views.py`). Until the SMS gateway is wired up
 * (`notifications/providers.py` is a deliberate stub), that response is the
 * only way to complete an invite, so the link is shown here to be copied. When
 * the gateway lands this panel keeps working unchanged and the link becomes a
 * fallback for a message that did not arrive — which, on Kenyan networks, is
 * worth keeping either way.
 */
function InvitesPanel({
  orgId,
  invites,
  onChanged,
}: {
  orgId: string;
  invites: Invite[];
  onChanged: () => void;
}) {
  const [phone, setPhone] = useState("");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [link, setLink] = useState<string | null>(null);

  function invite() {
    setSending(true);
    setError("");
    setLink(null);
    api
      .post(`/api/v1/orgs/${orgId}/invites/`, { phone: `+254${phone}`, role: "staff" })
      .then((created) => {
        setPhone("");
        if (created.token) setLink(`/join/${created.token}`);
        onChanged();
      })
      .catch((caught) =>
        setError(caught instanceof ApiError ? firstError(caught.body, "Could not save.") : "Could not invite.")
      )
      .finally(() => setSending(false));
  }

  function resend(id: string) {
    api
      .post(`/api/v1/orgs/${orgId}/invites/${id}/resend/`, {})
      .then((updated) => {
        if (updated.token) setLink(`/join/${updated.token}`);
        onChanged();
      })
      .catch(() => setError("Could not resend that."));
  }

  const pending = invites.filter((row) => row.status === "pending");

  return (
    <Section
      title="Staff logins"
      intro="Each person signs in as themselves, sees only their own day, and their bookings count towards their own numbers."
    >
      <ErrorPanel>{error}</ErrorPanel>

      {link ? (
        <div
          style={{
            padding: "var(--bn-space-6)",
            borderRadius: "var(--bn-radius-md)",
            background: "var(--bn-info-50)",
            color: "var(--bn-info-700)",
            display: "grid",
            gap: "var(--bn-space-3)",
          }}
        >
          <strong>Send them this link</strong>
          <code style={{ fontFamily: "var(--bn-font-mono)", wordBreak: "break-all" }}>{link}</code>
          <span style={{ fontSize: "var(--bn-text-body-sm-size)" }}>
            Shown once. If you lose it, resend the invite for a new one.
          </span>
        </div>
      ) : null}

      {pending.length ? (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: "var(--bn-space-4)" }}>
          {pending.map((row) => (
            <li
              key={row.id}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: "var(--bn-space-6)",
                padding: "var(--bn-space-4) var(--bn-space-6)",
                border: "1px solid var(--bn-line)",
                borderRadius: "var(--bn-radius-md)",
                flexWrap: "wrap",
              }}
            >
              <span style={{ fontFamily: "var(--bn-font-mono)" }}>{row.phone}</span>
              <span style={{ color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
                Invited {row.created_at.slice(0, 10)} · hasn&apos;t signed in yet
              </span>
              <Button
                variant="secondary"
                onClick={() => resend(row.id)}
                style={{ width: "auto", padding: "0 var(--bn-space-6)" }}
              >
                Resend
              </Button>
            </li>
          ))}
        </ul>
      ) : null}

      <div style={{ display: "flex", gap: "var(--bn-space-6)", alignItems: "end", flexWrap: "wrap" }}>
        <Field label="Their phone" hint="The number they will sign in with.">
          <NumberInput
            value={phone}
            onChange={(value) => setPhone(value.slice(0, 9))}
            prefix="+254"
            placeholder="712345678"
          />
        </Field>
        <Button
          onClick={invite}
          disabled={phone.length < 9 || sending}
          disabledReason={phone.length < 9 ? "Nine digits" : undefined}
          style={{ width: "auto", minWidth: 160 }}
        >
          {sending ? "Inviting…" : "Invite"}
        </Button>
      </div>
      <Note>
        Inviting someone does not create a chair, and adding a chair does not send anything. Do
        both for a stylist who takes bookings and signs in.
      </Note>
    </Section>
  );
}
