// Server-side base URL for the backend API. Inside docker-compose this points
// at the `backend` service; locally it falls back to localhost.
const API_URL = process.env.API_URL ?? "http://localhost:8000";

export type Health = {
  status: string;
  version: string;
  services: {
    database: string;
    redis: string;
  };
};

/**
 * Fetch the backend healthcheck. Returns `null` if the API is unreachable so
 * the page can render a graceful "offline" state instead of throwing.
 */
export async function getHealth(): Promise<Health | null> {
  try {
    const res = await fetch(`${API_URL}/api/v1/health/`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as Health;
  } catch {
    return null;
  }
}
