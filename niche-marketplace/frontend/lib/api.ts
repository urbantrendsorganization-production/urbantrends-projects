// Server-side data fetchers (used by server components). These talk to the API
// over the compose network and normalise media URLs for the browser.
import { API_BASE, toBrowserUrl } from "@/lib/config";
import type {
  Category,
  Health,
  Listing,
  Paginated,
  PublicProfile,
} from "@/lib/types";

/** Rewrite a listing's image URLs so the browser can load them. */
function normaliseListing(listing: Listing): Listing {
  return {
    ...listing,
    seller: { ...listing.seller, avatar: toBrowserUrl(listing.seller.avatar) },
    images: listing.images.map((img) => ({
      ...img,
      image: toBrowserUrl(img.image) ?? img.image,
      thumbnail: toBrowserUrl(img.thumbnail),
    })),
  };
}

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

/** Fetch the full category tree (flat list, all levels). */
export async function getCategories(): Promise<Category[]> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/categories/?limit=500`, {
      cache: "no-store",
    });
    if (!res.ok) return [];
    const data = (await res.json()) as Paginated<Category>;
    return data.results;
  } catch {
    return [];
  }
}

/** Fetch a single active listing by id (owners' drafts 403 → null here). */
export async function getListing(id: string | number): Promise<Listing | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/listings/${id}/`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return normaliseListing((await res.json()) as Listing);
  } catch {
    return null;
  }
}
