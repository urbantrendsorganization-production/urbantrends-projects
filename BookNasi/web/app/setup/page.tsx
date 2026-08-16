"use client";

/**
 * `/setup` — where a shop becomes bookable.
 *
 * Eleven slices built a booking engine, a payment flow and two dashboards, and
 * every one of them assumed a shop that already had hours, services and staff.
 * Nothing created one. An owner finished signup, landed on an empty dashboard,
 * and the only way forward was the Django admin. This is the screen that was
 * missing.
 *
 * ## One screen, not a wizard
 *
 * The design's onboarding is four ordered steps and its settings surface is a
 * sidebar of sections; those are the same information twice. What ships is the
 * ordering as a checklist and the sections beneath it, so a new owner works
 * down and a returning owner jumps in. Slice 11 was explicit that onboarding
 * is "somewhere an owner is sent by an empty dashboard, not somewhere a
 * returning owner is dumped" — a route that is always valid satisfies both
 * halves of that.
 *
 * ## Everything reloads together
 *
 * A write anywhere refetches the whole shop. That is more requests than a
 * surgical cache update and it is the right trade here: the checklist is
 * derived from every one of these tables at once, so a service saved without
 * refetching readiness leaves the list stating something that stopped being
 * true a second ago — on the one screen whose entire job is to say what is
 * still missing. This is a settings page on a laptop, not the booking flow on
 * 3G; §12's cost argument does not apply.
 *
 * ## Owners and managers only, and one tab that is narrower still
 *
 * `managing_roles_required` on every endpoint underneath, so this is a
 * courtesy rather than the control. A stylist who arrives here is sent to
 * their own day.
 *
 * **M-Pesa is owner-only.** It is the one endpoint in the product a manager
 * cannot reach — a manager sets prices and deposit rules, so they decide how
 * much is taken, but where it lands is a different act. The tab is hidden
 * rather than shown-and-refused, and the request is deliberately outside the
 * batch below: a 403 inside a `Promise.all` fails the whole load, so a
 * manager would lose hours, services and staff to a tab they cannot use.
 */

import { useCallback, useEffect, useState } from "react";

import { Checklist, type Readiness } from "../../components/setup/Checklist";
import { HoursEditor, type Closure, type Hours } from "../../components/setup/HoursEditor";
import { MpesaEditor, type Mpesa } from "../../components/setup/MpesaEditor";
import { PrivacyEditor, type ClientRow } from "../../components/setup/PrivacyEditor";
import { ServicesEditor, type Service } from "../../components/setup/ServicesEditor";
import { ShopForm, type Shop } from "../../components/setup/ShopForm";
import {
  StaffEditor,
  type Invite,
  type Staff,
  type StaffDetail,
} from "../../components/setup/StaffEditor";
import { ApiError, api } from "../../lib/api";

type Membership = {
  organization: string;
  organization_name: string;
  role: "owner" | "manager" | "staff";
};

const SECTIONS = [
  { id: "shop", label: "Shop" },
  { id: "hours", label: "Hours" },
  { id: "services", label: "Services" },
  { id: "staff", label: "Staff" },
  // Slice 14. Managing roles, not owner-only: a manager can see requests and
  // export, and gets a sentence where the Remove button would be. The person
  // most likely to field the phone call should not be the one who cannot see
  // that a request exists.
  { id: "privacy", label: "Data & privacy" },
];

//: Appended for an owner only. Kept out of `SECTIONS` rather than filtered out
//: of it at render time so that no code path can produce the tab for somebody
//: whose request for it would 403.
const OWNER_SECTIONS = [{ id: "mpesa", label: "M-Pesa" }];

export default function Setup() {
  const [org, setOrg] = useState<Membership | null>(null);
  const [memberships, setMemberships] = useState<Membership[] | null>(null);
  const [shops, setShops] = useState<Shop[] | null>(null);
  const [shopId, setShopId] = useState<string | null>(null);
  const [section, setSection] = useState("shop");

  const [hours, setHours] = useState<Hours[]>([]);
  const [closures, setClosures] = useState<Closure[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [staff, setStaff] = useState<Staff[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [details, setDetails] = useState<Record<string, StaffDetail>>({});
  const [openStaffId, setOpenStaffId] = useState<string | null>(null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [mpesa, setMpesa] = useState<Mpesa | null>(null);
  const [clients, setClients] = useState<ClientRow[]>([]);
  const [retention, setRetention] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get("/api/v1/auth/me/")
      .then((data) => {
        const managing = (data.memberships as Membership[]).filter(
          (row) => row.role === "owner" || row.role === "manager"
        );
        setMemberships(managing);
        if (managing.length) setOrg(managing[0]);
      })
      .catch((caught) => {
        // Same rule as both dashboards: not signed in is a destination, not an
        // error to render.
        if (caught instanceof ApiError && (caught.status === 401 || caught.status === 403)) {
          window.location.assign("/signin");
          return;
        }
        setError("Could not reach the API. Check your connection.");
      });
  }, []);

  const loadShops = useCallback(() => {
    if (!org) return;
    api
      .get(`/api/v1/orgs/${org.organization}/shops/`)
      .then((data) => {
        const rows: Shop[] = data.results ?? data;
        setShops(rows);
        setShopId((current) => current ?? rows[0]?.id ?? null);
      })
      .catch(() => setError("Could not load your shops."));
  }, [org]);

  useEffect(loadShops, [loadShops]);

  const loadShop = useCallback(() => {
    if (!org || !shopId) return;
    const orgId = org.organization;
    // Whole paths, not a shared `base` variable. `core/tests/test_frontend_routes.py`
    // resolves every URL the frontend builds against Django's URLconf, and it
    // can only do that for a path that is readable at the point it is
    // requested — a base assembled two lines up is exactly the shape that let
    // the manage page 404 for four slices.
    Promise.all([
      api.get(`/api/v1/orgs/${orgId}/shops/${shopId}/opening-hours/`),
      api.get(`/api/v1/orgs/${orgId}/shops/${shopId}/closures/`),
      api.get(`/api/v1/orgs/${orgId}/shops/${shopId}/services/`),
      api.get(`/api/v1/orgs/${orgId}/shops/${shopId}/staff/`),
      api.get(`/api/v1/orgs/${orgId}/invites/`),
      api.get(`/api/v1/orgs/${orgId}/shops/${shopId}/readiness/`),
    ])
      .then(([hoursData, closureData, serviceData, staffData, inviteData, readinessData]) => {
        setHours(rows(hoursData));
        setClosures(rows(closureData));
        setServices(rows(serviceData));
        setStaff(rows(staffData));
        setInvites(rows(inviteData));
        setReadiness(readinessData);
        setError("");
      })
      .catch((caught) => {
        if (caught instanceof ApiError && caught.status === 403) {
          setError("Only an owner or a manager can change these settings.");
          return;
        }
        setError("That did not load. Try again.");
      });
  }, [org, shopId]);

  useEffect(loadShop, [loadShop]);

  // Owner only, and outside the batch above on purpose. A 403 inside a
  // `Promise.all` rejects the whole thing, so folding this in would cost a
  // manager their hours, services and staff to a tab they cannot open.
  const loadMpesa = useCallback(() => {
    if (!org || !shopId || org.role !== "owner") {
      setMpesa(null);
      return;
    }
    const orgId = org.organization;
    api
      .get(`/api/v1/orgs/${orgId}/shops/${shopId}/mpesa/`)
      .then(setMpesa)
      .catch(() => setMpesa(null));
  }, [org, shopId]);

  useEffect(loadMpesa, [loadMpesa]);

  // Org-scoped, not shop-scoped — CLAUDE.md §3 and §9 agree here: the
  // organization is the controller, and a data subject's record spans every
  // branch they have visited. So this hangs off `org` and not `shopId`, and
  // does not reload when the shop selector changes.
  const loadPrivacy = useCallback(() => {
    if (!org) return;
    const orgId = org.organization;
    Promise.all([
      api.get(`/api/v1/orgs/${orgId}/clients/`),
      api.get(`/api/v1/orgs/${orgId}/clients/retention/`),
    ])
      .then(([clientData, policy]) => {
        setClients(rows(clientData));
        setRetention(policy.statement);
      })
      .catch(() => setRetention(""));
  }, [org]);

  useEffect(loadPrivacy, [loadPrivacy]);

  // One staff member's days and services, fetched when their row is opened.
  // Kept out of the batch above because a twelve-chair shop would otherwise
  // pay twenty-four requests to draw a list nobody has expanded.
  const loadDetail = useCallback(
    (staffId: string) => {
      if (!org) return;
      const orgId = org.organization;
      Promise.all([
        api.get(`/api/v1/orgs/${orgId}/staff/${staffId}/working-hours/`),
        api.get(`/api/v1/orgs/${orgId}/staff/${staffId}/services/`),
      ])
        .then(([hoursData, skillData]) =>
          setDetails((prev) => ({
            ...prev,
            [staffId]: { hours: rows(hoursData), skills: rows(skillData) },
          }))
        )
        .catch(() => setError("Could not load that person's days."));
    },
    [org]
  );

  useEffect(() => {
    if (openStaffId) loadDetail(openStaffId);
  }, [openStaffId, loadDetail]);

  /** After any write. Reloads the shop, and the open person if there is one. */
  const refresh = useCallback(() => {
    loadShop();
    if (openStaffId) loadDetail(openStaffId);
  }, [loadShop, openStaffId, loadDetail]);

  if (error && !shops) return <Shell>{error}</Shell>;
  if (!memberships) return <Shell>Loading…</Shell>;
  if (!memberships.length) {
    return <Shell>Shop settings are for owners and managers. Your day is at /staff.</Shell>;
  }
  if (!shops) return <Shell>Loading…</Shell>;

  const shop = shops.find((row) => row.id === shopId) ?? null;
  const orgId = org?.organization ?? "";

  return (
    <main
      style={{
        maxWidth: 900,
        margin: "0 auto",
        padding: "var(--bn-space-9) var(--bn-space-gutter)",
        display: "grid",
        gap: "var(--bn-space-8)",
      }}
    >
      <header
        style={{
          display: "flex",
          gap: "var(--bn-space-6)",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          borderBottom: "1px solid var(--bn-line)",
          paddingBottom: "var(--bn-space-6)",
        }}
      >
        <span style={{ display: "flex", gap: "var(--bn-space-5)", alignItems: "baseline" }}>
          <span style={{ fontFamily: "var(--bn-font-display)", fontWeight: 700 }}>BookNasi</span>
          <span style={{ color: "var(--bn-ink-70)" }}>{org?.organization_name}</span>
        </span>
        <nav style={{ display: "flex", gap: "var(--bn-space-5)", flexWrap: "wrap" }}>
          <a href="/owner" style={LINK}>
            Dashboard
          </a>
          <a href="/staff" style={LINK}>
            Today
          </a>
        </nav>
      </header>

      {/* No shop at all: one form, and nothing else is meaningful yet. */}
      {!shops.length ? (
        <ShopForm
          orgId={orgId}
          shop={null}
          onSaved={(created) => {
            setShops([created]);
            setShopId(created.id);
          }}
        />
      ) : (
        <>
          {shops.length > 1 ? (
            <select
              value={shopId ?? ""}
              onChange={(event) => {
                setShopId(event.target.value);
                setOpenStaffId(null);
              }}
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
              {shops.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
          ) : null}

          {readiness ? (
            <Checklist
              readiness={readiness}
              onGo={setSection}
              reachable={[...SECTIONS, ...(org?.role === "owner" ? OWNER_SECTIONS : [])].map(
                (tab) => tab.id
              )}
            />
          ) : null}

          <nav
            style={{
              display: "flex",
              gap: "var(--bn-space-4)",
              flexWrap: "wrap",
              borderBottom: "1px solid var(--bn-line)",
            }}
          >
            {[...SECTIONS, ...(org?.role === "owner" ? OWNER_SECTIONS : [])].map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setSection(tab.id)}
                style={{
                  minHeight: "var(--bn-target-control)",
                  padding: "0 var(--bn-space-7)",
                  background: "transparent",
                  border: "none",
                  borderBottom:
                    section === tab.id ? "2px solid var(--bn-accent)" : "2px solid transparent",
                  color: section === tab.id ? "var(--bn-ink)" : "var(--bn-ink-45)",
                  fontWeight: section === tab.id ? 600 : 400,
                  fontFamily: "var(--bn-font-ui)",
                  fontSize: "var(--bn-text-body-size)",
                  cursor: "pointer",
                }}
              >
                {tab.label}
              </button>
            ))}
          </nav>

          {error ? (
            <p role="alert" style={{ margin: 0, color: "var(--bn-fail-700)" }}>
              {error}
            </p>
          ) : null}

          {shop && section === "shop" ? (
            <ShopForm orgId={orgId} shop={shop} onSaved={() => loadShops()} />
          ) : null}

          {shop && section === "hours" ? (
            <HoursEditor
              orgId={orgId}
              shopId={shop.id}
              hours={hours}
              closures={closures}
              onChanged={refresh}
            />
          ) : null}

          {shop && section === "services" ? (
            <ServicesEditor
              orgId={orgId}
              shopId={shop.id}
              services={services}
              refundWindowHours={shop.refund_window_hours}
              depositCreditDays={shop.deposit_credit_days}
              onChanged={() => {
                loadShops();
                loadShop();
              }}
            />
          ) : null}

          {shop && section === "staff" ? (
            <StaffEditor
              orgId={orgId}
              shopId={shop.id}
              staff={staff}
              services={services}
              invites={invites}
              details={details}
              openStaffId={openStaffId}
              onOpenStaff={setOpenStaffId}
              onChanged={refresh}
            />
          ) : null}

          {section === "privacy" ? (
            <PrivacyEditor
              orgId={orgId}
              clients={clients}
              retentionStatement={retention}
              canErase={org?.role === "owner"}
              onChanged={loadPrivacy}
            />
          ) : null}

          {shop && section === "mpesa" && mpesa ? (
            <MpesaEditor
              orgId={orgId}
              shopId={shop.id}
              mpesa={mpesa}
              onChanged={() => {
                loadMpesa();
                // The readiness checklist reads `can_take_deposits`, so a
                // connection saved here changes the list at the top of the same
                // screen. Without this the owner connects M-Pesa and the
                // checklist goes on telling them to.
                loadShop();
              }}
            />
          ) : null}
        </>
      )}
    </main>
  );
}

const LINK = {
  minHeight: "var(--bn-target-control)",
  display: "inline-flex",
  alignItems: "center",
  padding: "0 var(--bn-space-5)",
  color: "var(--bn-ink-70)",
  textDecoration: "none",
};

/** DRF pages some lists and not others; both shapes arrive here. */
function rows<T>(data: { results?: T[] } | T[]): T[] {
  return Array.isArray(data) ? data : (data.results ?? []);
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div style={{ padding: "var(--bn-space-9)", color: "var(--bn-ink-45)" }}>{children}</div>;
}
