/**
 * The API is reached same-origin, always. In development that is this rewrite;
 * in production it is Caddy, doing the same thing one layer up (CLAUDE.md §2).
 *
 * ## Why a proxy and not CORS
 *
 * Slice 11 found that the authenticated frontend could not reach the API from a
 * browser at all. `lib/api.ts` pointed at `http://localhost:8000` while Next
 * serves `:3000`, and it sends `credentials: "include"` — a credentialed
 * cross-origin request to `/api/v1/`, which `core/cors.py` deliberately answers
 * with no CORS headers whatsoever. Every owner and staff request was refused by
 * the browser before it left the machine. It survived slices 4 and 9 because
 * those screens are verified by `render.test.tsx` and `owner.test.tsx`, which
 * assert on server-rendered markup with no browser involved.
 *
 * There were two ways out and only one of them is defensible. Adding
 * credentialed CORS for `/api/v1/` would mean an origin allowlist plus
 * `Access-Control-Allow-Credentials` on the org-scoped surface — reintroducing,
 * one slice later, exactly the reflect-and-credential shape `core/cors.py` was
 * written to prevent, on the endpoints that read a shop's takings. The proxy
 * instead makes the browser's own same-origin policy true again: cookies are
 * same-site, CSRF works the way Django expects, and `/api/v1/` continues to
 * need no CORS at all.
 *
 * It also removes the way this class of bug hid. Dev now reaches the API the
 * same way production does, so a cross-origin mistake cannot be invisible
 * locally and fatal on Hetzner.
 *
 * The public surface keeps its `Access-Control-Allow-Origin: *` — that header
 * exists for third-party hosts embedding the widget, which is the only caller
 * that genuinely is on another origin. Nothing here weakens it and nothing here
 * depends on it.
 */

/** Where Django actually listens. Only this file and Caddy know. */
const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
module.exports = {
  reactStrictMode: true,

  // Django's URLs all end in a slash; Next's default is to 308 the slash away
  // before a rewrite ever runs. Without this every proxied request answers
  // "308 Permanent Redirect" to a path Django does not route — which is how
  // this was found, by curling the proxy rather than reasoning about it.
  //
  // The redirect is skipped rather than `trailingSlash: true` because that
  // would also add slashes to the app's own routes, changing every page URL to
  // fix an API one.
  skipTrailingSlashRedirect: true,

  async rewrites() {
    return [
      // Everything under /api, including the public booking surface, the
      // org-scoped surface and the M-Pesa callback path. One prefix, because a
      // per-endpoint list is a list somebody forgets to extend — which is the
      // same failure that put a missing `/api/public/v1` in the manage page.
      //
      // Two rules rather than one, and the order matters. `:path*` captures
      // segments and rejoins them without a trailing slash, so a single rule
      // hands Django `/api/v1/auth/login` — which it does not route. On a GET
      // that is a 301 nobody notices; on a POST, `APPEND_SLASH` cannot redirect
      // a request with a body, so Django raises outright. The slashed source
      // is matched first and puts the slash back on the destination.
      { source: "/api/:path*/", destination: `${API_ORIGIN}/api/:path*/` },
      { source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` },
    ];
  },
};
