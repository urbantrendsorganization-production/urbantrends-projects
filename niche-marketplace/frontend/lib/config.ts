// The API is reachable under two names depending on where code runs:
//  - browser (client components): via the host, e.g. http://localhost:8000
//  - server components inside docker: via the compose service, http://backend:8000
export const PUBLIC_API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
