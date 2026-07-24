// Shared helpers for the browse directory — used by both the server page and
// the client "load more" so the two always send the API the same parameters.
import { PUBLIC_API_BASE } from "@/lib/config";
import type { CursorPage, Listing, ListingFeed, ListingSort } from "@/lib/types";

export const SORT_OPTIONS: { value: ListingSort; label: string }[] = [
  { value: "newest", label: "Newest" },
  { value: "price_asc", label: "Price: low to high" },
  { value: "price_desc", label: "Price: high to low" },
];

// Single-value params the directory understands (attr_* and condition handled
// separately, below).
const PASSTHROUGH = ["q", "category", "price_min", "price_max", "location", "sort"];

/** Whitelist the directory params from an arbitrary source into a clean query. */
export function buildListingQuery(source: URLSearchParams): URLSearchParams {
  const out = new URLSearchParams();
  for (const key of PASSTHROUGH) {
    const value = source.get(key);
    if (value) out.set(key, value);
  }
  for (const value of source.getAll("condition")) {
    if (value) out.append("condition", value);
  }
  source.forEach((value, key) => {
    if (key.startsWith("attr_") && value) out.set(key, value);
  });
  return out;
}

/** Build a URLSearchParams from Next's plain searchParams object. */
export function toSearchParams(
  obj: Record<string, string | string[] | undefined>,
): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(obj)) {
    if (Array.isArray(value)) value.forEach((v) => params.append(key, v));
    else if (value != null) params.set(key, value);
  }
  return params;
}

/** Pull the opaque cursor token out of a DRF ``next`` URL. */
export function cursorFrom(next: string | null): string | null {
  if (!next) return null;
  try {
    return new URL(next).searchParams.get("cursor");
  } catch {
    return null;
  }
}

/**
 * Client-side fetch of the next page. Runs in the browser, so it hits the
 * public API host and image URLs already resolve — no rewriting needed.
 */
export async function fetchNextListings(
  query: URLSearchParams,
  cursor: string,
): Promise<ListingFeed> {
  const params = buildListingQuery(query);
  params.set("cursor", cursor);
  try {
    const res = await fetch(`${PUBLIC_API_BASE}/api/v1/listings/?${params}`);
    if (!res.ok) return { results: [], nextCursor: null };
    const data = (await res.json()) as CursorPage<Listing>;
    return { results: data.results, nextCursor: cursorFrom(data.next) };
  } catch {
    return { results: [], nextCursor: null };
  }
}
