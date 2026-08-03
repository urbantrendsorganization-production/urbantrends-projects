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
  releaseHold(holdId: string): Promise<Hold>;
}

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
}

export function httpTransport({
  baseUrl,
  fetchImpl,
  csrfToken,
}: HttpTransportOptions): Transport {
  const root = `${baseUrl.replace(/\/$/, "")}/api/public/v1`;

  async function call(path: string, init?: { method?: string; body?: unknown }) {
    const method = init?.method ?? "GET";
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const token = method !== "GET" && csrfToken ? csrfToken() : "";
    if (token) headers["X-CSRFToken"] = token;

    const response = await fetchImpl(`${root}${path}`, {
      method,
      headers,
      body: init?.body === undefined ? undefined : JSON.stringify(init.body),
      credentials: "include",
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
  };
}
