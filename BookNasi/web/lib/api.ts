/**
 * The one place the staff app talks to the API.
 *
 * Session cookie plus CSRF, matching `accounts/views.py`. No token in
 * localStorage: a shop phone is a shared, unlocked device left on a counter,
 * and a bearer token sitting in storage on one is a worse artefact than a
 * cookie the browser will at least scope and expire.
 *
 * ## Retry, and what it is not
 *
 * Slice 4 ships **optimistic render, retry, and a stale-read banner** — not the
 * full offline write queue (CLAUDE.md §12). The difference is deliberate and
 * visible here: `postWithRetry` keeps trying for as long as the screen is open
 * and then gives up *loudly*. Nothing is persisted to disk, so a write that has
 * not landed by the time the tab closes is gone, and the staff member has been
 * told so rather than left believing it saved.
 *
 * Every retried write carries a `client_request_id`, generated once per attempt
 * *set* and reused across retries. Without it the second attempt of a request
 * the server already accepted inserts a second appointment, the exclusion
 * constraint refuses it, and the stylist is told that their own walk-in just
 * took their slot.
 */

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  body: any;
  constructor(status: number, body: any) {
    super(typeof body?.detail === "string" ? body.detail : `Request failed (${status})`);
    this.status = status;
    this.body = body;
  }
}

function readCookie(name: string): string {
  const match = document.cookie.match(new RegExp(`(^| )${name}=([^;]+)`));
  return match ? decodeURIComponent(match[2]) : "";
}

async function request(path: string, init: RequestInit = {}) {
  const method = (init.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init.headers as Record<string, string>) ?? {}),
  };
  if (method !== "GET") headers["X-CSRFToken"] = readCookie("csrftoken");

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    method,
    headers,
    credentials: "include",
  });

  const text = await response.text();
  const body = text ? JSON.parse(text) : null;
  if (!response.ok) throw new ApiError(response.status, body);
  return body;
}

export const api = {
  get: (path: string) => request(path),
  post: (path: string, payload: unknown) =>
    request(path, { method: "POST", body: JSON.stringify(payload) }),
};

/** A stable id for one logical write, reused by every retry of it. */
export function newRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

const BACKOFF_MS = [0, 1200, 3000, 6000];

/**
 * Post, retrying only what is worth retrying.
 *
 * A 4xx is an answer — a collision, a refusal, a validation error — and
 * retrying it just delays the moment the staff member finds out. Only network
 * failures and 5xx are attempted again, which is exactly the set that means
 * "the shop's connection dropped", the case this exists for.
 *
 * `onAttempt` reports each try so the row can show what is happening rather
 * than a spinner that says nothing.
 */
export async function postWithRetry(
  path: string,
  payload: Record<string, unknown>,
  { onAttempt }: { onAttempt?: (attempt: number, total: number) => void } = {}
) {
  let lastError: unknown;
  for (let attempt = 0; attempt < BACKOFF_MS.length; attempt += 1) {
    if (BACKOFF_MS[attempt]) await new Promise((r) => setTimeout(r, BACKOFF_MS[attempt]));
    onAttempt?.(attempt + 1, BACKOFF_MS.length);
    try {
      return await api.post(path, payload);
    } catch (error) {
      lastError = error;
      const retryable = !(error instanceof ApiError) || error.status >= 500;
      if (!retryable) throw error;
    }
  }
  throw lastError;
}
