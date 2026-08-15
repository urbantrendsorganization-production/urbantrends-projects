/**
 * The one interface the flow needs from the outside world.
 *
 * An interface rather than a direct `fetch` because the flow has to be
 * drivable without a network: the tests in this package run under `node --test`
 * with a hand-written transport and no server, which is what makes them
 * milliseconds rather than a fixture. Slice 10's widget will pass its own,
 * because a host page may want the requests to go through its own client.
 *
 * `fetchImpl` is injected for the same reason and one more: this file must not
 * touch a global, or `check-no-framework.mjs` fails it. See the README.
 */

import type { Availability, Hold, HoldRequest, Service, Shop, StaffOption } from "./types";

export interface Transport {
  getShop(slug: string): Promise<Shop>;
  getServices(slug: string): Promise<Service[]>;
  getStaff(slug: string, serviceId: string): Promise<StaffOption[]>;
  getAvailability(
    slug: string,
    serviceId: string,
    date: string,
    staffId?: string
  ): Promise<Availability>;
  createHold(slug: string, request: HoldRequest): Promise<Hold>;
  getHold(holdId: string): Promise<Hold>;
  /** Slice 7's slotLost remedy: carry a paid deposit onto a freshly held slot. */
  repointPayment(supportCode: string, holdId: string): Promise<unknown>;
  releaseHold(holdId: string): Promise<Hold>;
  /** A second STK prompt for a hold that already has one. Refused by the
   *  server past its rate, count or grace ceiling — see `flow.resend`. */
  resendPush(holdId: string): Promise<Hold>;
}

/**
 * Where the unauthenticated surface lives. Written once, here.
 *
 * Slice 11 found out why that matters. This prefix used to exist only as a
 * literal inside `httpTransport`, so the two routes that go through the
 * transport were right and the one screen that hand-rolled its fetches —
 * `web/app/m/[token]`, the manage link an SMS sends a client — asked for
 * `/manage/<token>/` and got a 404 on every request, from the day it shipped.
 * A rendering test cannot see a wrong URL, so nothing noticed.
 *
 * Exported rather than duplicated, and `core/tests/test_frontend_routes.py`
 * now walks every path the frontend builds and resolves it against Django's
 * real URLconf — because "the prefix is written once" is a convention, and the
 * test is the thing that holds.
 */
export const PUBLIC_API_PREFIX = "/api/public/v1";

export class TransportError extends Error {
  status: number;
  body: any;
  constructor(status: number, body: any) {
    super(typeof body?.detail === "string" ? body.detail : `Request failed (${status})`);
    this.status = status;
    this.body = body;
  }
}

export type FetchLike = (url: string, init?: any) => Promise<any>;

export interface HttpTransportOptions {
  baseUrl: string;
  fetchImpl: FetchLike;
  /** Sent on unsafe requests. Absent inside a widget on another origin. */
  csrfToken?: () => string;
  /**
   * Slice 10. `"omit"` inside the widget, and the default stays `"include"` so
   * the standalone app is unchanged.
   *
   * The widget runs on a host's origin, and `core/cors.py` answers
   * `Access-Control-Allow-Origin: *` with credentials never allowed — a
   * combination the browser refuses outright if the request carries them. That
   * refusal is the point rather than an obstacle: this surface is
   * unauthenticated and shop-scoped by slug, it has no use for a cookie, and a
   * widget that sent one anyway would be opening a credentialed cross-origin
   * channel to an API that has no idea what to do with it. Failing at the
   * browser is the cheapest place for that to be noticed.
   */
  credentials?: "include" | "omit" | "same-origin";
}

export function httpTransport({
  baseUrl,
  fetchImpl,
  csrfToken,
  credentials = "include",
}: HttpTransportOptions): Transport {
  const root = `${baseUrl.replace(/\/$/, "")}${PUBLIC_API_PREFIX}`;

  async function call(path: string, init?: { method?: string; body?: unknown }) {
    const method = init?.method ?? "GET";
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const token = method !== "GET" && csrfToken ? csrfToken() : "";
    if (token) headers["X-CSRFToken"] = token;

    const response = await fetchImpl(`${root}${path}`, {
      method,
      headers,
      body: init?.body === undefined ? undefined : JSON.stringify(init.body),
      credentials,
    });
    const text = await response.text();
    const body = text ? JSON.parse(text) : null;
    if (!response.ok) throw new TransportError(response.status, body);
    return body;
  }

  return {
    getShop: (slug) => call(`/shops/${slug}/`),
    getServices: (slug) => call(`/shops/${slug}/services/`),
    getStaff: (slug, serviceId) => call(`/shops/${slug}/services/${serviceId}/staff/`),
    getAvailability: (slug, serviceId, date, staffId) => {
      const query = new URLSearchParams({ date });
      if (staffId) query.set("staff", staffId);
      return call(`/shops/${slug}/services/${serviceId}/availability/?${query}`);
    },
    createHold: (slug, request) =>
      call(`/shops/${slug}/holds/`, { method: "POST", body: request }),
    getHold: (holdId) => call(`/holds/${holdId}/`),
    releaseHold: (holdId) => call(`/holds/${holdId}/release/`, { method: "POST" }),
    resendPush: (holdId) => call(`/holds/${holdId}/resend/`, { method: "POST" }),
    repointPayment: (supportCode, holdId) =>
      call(`/payments/${supportCode}/repoint/`, { method: "POST", body: { hold: holdId } }),
  };
}
