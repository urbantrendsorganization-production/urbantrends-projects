// Server-side data fetchers (used by server components). These talk to the API
// over the compose network and normalise media URLs for the browser.
import { API_BASE, toBrowserUrl } from "@/lib/config";
import type { Health, PublicProfile } from "@/lib/types";

/**
 * Fetch the backend healthcheck. Returns `null` if the API is unreachable so
 * the page can render a graceful "offline" state instead of throwing.
 */
export async function getHealth(): Promise<Health | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/health/`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as Health;
  } catch {
    return null;
  }
}

/** Fetch a user's public profile. Returns `null` on 404 / error. */
export async function getPublicProfile(
  id: string | number,
): Promise<PublicProfile | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/users/${id}/`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    const data = (await res.json()) as PublicProfile;
    return { ...data, avatar: toBrowserUrl(data.avatar) };
  } catch {
    return null;
  }
}
