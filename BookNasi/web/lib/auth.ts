/**
 * Who is signed in, and where that person belongs.
 *
 * `/api/v1/auth/me/` answers all of it in one request — the user, their
 * memberships, and the chairs they actually work at. Slice 4 added `chairs` for
 * exactly this reason: the staff app opens on a shop phone on 3G with a client
 * already waiting, and three round trips to find out whose day to draw is three
 * round trips too many.
 */

import { api } from "./api";

export type Role = "owner" | "manager" | "staff";

export type Membership = {
  organization: string;
  organization_name: string;
  role: Role;
};

export type Chair = {
  staff_id: string;
  display_name: string;
  shop_id: string;
  shop_name: string;
  organization_id: string;
};

export type Me = {
  user: { id: string; phone: string; full_name: string };
  memberships: Membership[];
  chairs: Chair[];
};

/** The roles that may read money. Mirrors `OrgScopedMixin.managing_roles`. */
export const MANAGING: Role[] = ["owner", "manager"];

export function manages(me: Me): boolean {
  return me.memberships.some((row) => MANAGING.includes(row.role));
}

/**
 * Where a person lands after signing in.
 *
 * Owners and managers get the dashboard, everyone else gets their own day. An
 * owner who is also a stylist — which is most single-chair shops — gets the
 * dashboard, because they can reach their own day from it and the reverse is
 * not true.
 *
 * Deliberately never `/setup`. Onboarding is somewhere you are *sent* by an
 * owner dashboard with nothing in it, not somewhere a returning owner is
 * dumped because a query happened to come back empty on a slow morning.
 */
export function landingFor(me: Me): string {
  if (manages(me)) return "/owner";
  if (me.chairs.length) return "/staff";
  // A membership with no chair and no managing role: invited, accepted, and
  // not yet put on a rota. Their own day is still the honest destination — it
  // says there is nothing today rather than pretending they have no account.
  return "/staff";
}

export function fetchMe(): Promise<Me> {
  return api.get("/api/v1/auth/me/");
}

/**
 * The first error a DRF response carries, as a sentence.
 *
 * DRF answers `{"field": ["..."], "non_field_errors": ["..."]}` and sometimes
 * `{"detail": "..."}`. The screens render one line, so this picks it — and
 * prefers the non-field message, because on these forms it is the one that
 * says the useful thing ("That phone number and password do not match") while
 * the field errors are usually a restatement.
 */
export function firstError(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const data = body as Record<string, unknown>;
  if (typeof data.detail === "string") return data.detail;
  const keys = ["non_field_errors", ...Object.keys(data)];
  for (const key of keys) {
    const value = data[key];
    if (typeof value === "string") return value;
    if (Array.isArray(value) && typeof value[0] === "string") return value[0];
  }
  return fallback;
}
