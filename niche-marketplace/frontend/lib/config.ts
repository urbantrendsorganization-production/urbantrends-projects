// The API is reachable under two names depending on where code runs:
//  - browser (client components): via the host, e.g. http://localhost:8000
//  - server components inside docker: via the compose service, http://backend:8000

/**
 * Resolve an API base URL, refusing to fall back to a dev default in a
 * production build.
 *
 * `NEXT_PUBLIC_*` is inlined at BUILD time, not read at runtime. A production
 * build with the variable unset therefore bakes `http://localhost:8000` into
 * the client bundle, deploys green, and only fails when a user clicks
 * something — every request goes to the visitor's own machine. Failing the
 * build turns that into an obvious error while it can still be fixed.
 */
function apiBase(name: string, value: string | undefined, devFallback: string): string {
  if (value) return value;
  if (process.env.NODE_ENV === "production") {
    throw new Error(
      `${name} is not set. Production builds must point at the deployed API ` +
        `(e.g. https://marketplace.urbantrends.dev); falling back to ` +
        `${devFallback} would bake a dev URL into the bundle. Set it in the ` +
        `Vercel project's environment variables and redeploy WITHOUT the ` +
        `build cache so the value is re-inlined.`,
    );
  }
  return devFallback;
}

export const PUBLIC_API_BASE = apiBase(
  "NEXT_PUBLIC_API_URL",
  process.env.NEXT_PUBLIC_API_URL,
  "http://localhost:8000",
);

// Server-only, so it is read at runtime and can safely default to the public
// base — which is itself already guaranteed non-fallback in production.
export const API_BASE = process.env.API_URL ?? PUBLIC_API_BASE;

/**
 * Rewrite an absolute media/URL produced server-side (pointing at the internal
 * compose host) so the browser can actually load it.
 */
export function toBrowserUrl(url: string | null): string | null {
  if (!url) return url;
  if (API_BASE !== PUBLIC_API_BASE && url.startsWith(API_BASE)) {
    return PUBLIC_API_BASE + url.slice(API_BASE.length);
  }
  return url;
}
