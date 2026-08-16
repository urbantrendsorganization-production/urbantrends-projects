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

/**
 * Empty, meaning same-origin, and it should stay that way.
 *
 * Every request goes through the rewrite in `next.config.js` in development and
 * through Caddy in production, so the browser only ever talks to the origin it
 * loaded the page from. That is not a convenience — it is what makes the
 * session cookie same-site, CSRF work the way Django expects, and `/api/v1/`
 * safe to leave without any CORS headers at all.
 *
 * The override exists for the case this file cannot serve: something rendering
 * these components against an API on a genuinely different origin. Setting it
 * puts every authenticated call back into credentialed cross-origin territory,
 * where `core/cors.py` will — correctly — refuse it. See `next.config.js`.
 */
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

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

/**
 * The CSRF cookie, fetched once if the browser does not already have it.
 *
 * Django only sets `csrftoken` when something calls `get_token`, which is what
 * `/api/v1/auth/csrf/` exists to do. That endpoint shipped in slice 1 and
 * nothing ever called it: every screen so far either read (no token needed) or
 * was reached by a developer whose browser still had a cookie from a previous
 * session. A genuinely new visitor — which is every owner signing up — has no
 * cookie, and their first authenticated write fails.
 *
 * Lazy rather than on boot, and this is the deliberate part. The public booking
 * page is opened cold from a WhatsApp link on 3G, where the design's whole
 * budget is sixty seconds to a paid deposit; it never writes through this
 * module, so it must never pay a round trip for a token it will not use. The
 * cost lands on the first write, where it is one request against an action the
 * client just chose to take.
 *
 * The promise is cached so that two writes racing on page load prime once, and
 * cleared on failure so a later write can try again rather than inheriting a
 * dead promise for the life of the tab.
 */
let priming: Promise<void> | null = null;

async function ensureCsrfToken(): Promise<void> {
  if (readCookie("csrftoken")) return;
  priming ??= fetch(`${API_BASE}/api/v1/auth/csrf/`, { credentials: "include" })
    .then(() => undefined)
    .catch((error) => {
      priming = null;
      throw error;
    });
  // A failure here is not fatal on its own: the request below may still be one
  // Django does not check a token for, and its own error is a better one to
  // report than "could not fetch a token".
  await priming.catch(() => undefined);
}

async function request(path: string, init: RequestInit = {}) {
  const method = (init.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init.headers as Record<string, string>) ?? {}),
  };
  if (method !== "GET") {
    await ensureCsrfToken();
    // Read after priming, not before: `django.contrib.auth.login` rotates the
    // token, so the cookie that matters is the one present at send time.
    headers["X-CSRFToken"] = readCookie("csrftoken");
  }

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

/**
 * The org-and-shop scope every staff and owner path hangs off, as a function
 * that takes the rest of the path.
 *
 * Curried so the endpoint is a **literal at the point it is requested**:
 * `shop("/walk-in/options/")` rather than `` `${base}/walk-in/options/` ``
 * with `base` arriving as a prop from two components away. That is not a style
 * preference — `core/tests/test_frontend_routes.py` resolves every path the
 * frontend builds against Django's URLconf, and it cannot resolve a base it
 * cannot see. A URL assembled from an invisible variable is exactly the shape
 * that let the manage page ask for `/manage/<token>/` for four slices.
 */
export const shopScope =
  (orgId: string, shopId: string) =>
  (path: string) =>
    `/api/v1/orgs/${orgId}/shops/${shopId}${path}`;

/**
 * `patch` and `delete` arrived with the setup screen, and only there.
 *
 * Nothing before it edited configuration: the booking flow creates, the staff
 * app transitions a status through its own POST endpoints, and the dashboard
 * only reads. Shop settings is the first screen that changes a row that
 * already exists and removes one that should not — an opening-hours row for a
 * day the shop no longer trades, a service link ticked by mistake.
 *
 * `del` rather than `delete` because `delete` is a reserved word; the method
 * on the wire is the real one. Note what DELETE means on this API: shops,
 * staff and services deactivate rather than disappear
 * (`DeactivateInsteadOfDeleteMixin`), because appointments reference them and
 * CLAUDE.md §9 requires history to survive. Only the pure-configuration rows —
 * hours, leave, closures, staff-service links — are genuinely removed.
 */
export const api = {
  get: (path: string) => request(path),
  post: (path: string, payload: unknown) =>
    request(path, { method: "POST", body: JSON.stringify(payload) }),
  patch: (path: string, payload: unknown) =>
    request(path, { method: "PATCH", body: JSON.stringify(payload) }),
  del: (path: string) => request(path, { method: "DELETE" }),
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
