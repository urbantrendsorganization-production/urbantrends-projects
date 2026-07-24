import Link from "next/link";

import { formatPrice } from "@/lib/catalog";
import type { Listing } from "@/lib/types";

// Deterministic soft gradient for listings without a photo, so the grid still
// looks intentional rather than broken.
const PLACEHOLDERS = [
  "from-blue-100 to-indigo-100 text-indigo-400",
  "from-emerald-100 to-teal-100 text-teal-500",
  "from-amber-100 to-orange-100 text-orange-400",
  "from-rose-100 to-pink-100 text-pink-400",
  "from-violet-100 to-purple-100 text-purple-400",
  "from-cyan-100 to-sky-100 text-sky-500",
];

export function ListingCard({ listing }: { listing: Listing }) {
  const image = listing.images[0];
  const thumb = image?.thumbnail ?? image?.image ?? null;
  const palette = PLACEHOLDERS[listing.id % PLACEHOLDERS.length];

  return (
    <Link
      href={`/listings/${listing.id}`}
      className="group flex flex-col overflow-hidden rounded-2xl border border-neutral-200 bg-white transition hover:-translate-y-0.5 hover:shadow-md"
    >
      <div className="relative aspect-square overflow-hidden bg-neutral-100">
        {thumb ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={thumb}
            alt={listing.title}
            loading="lazy"
            className="h-full w-full object-cover transition duration-300 group-hover:scale-105"
          />
        ) : (
          <div
            className={`flex h-full w-full items-center justify-center bg-gradient-to-br ${palette}`}
          >
            <span className="px-4 text-center text-xs font-semibold uppercase tracking-wide">
              {listing.category.name}
            </span>
          </div>
        )}
        {listing.status === "reserved" ? (
          <span className="absolute left-2 top-2 rounded-full bg-amber-500/95 px-2 py-0.5 text-[11px] font-semibold text-white">
            Reserved
          </span>
        ) : null}
      </div>

      <div className="flex flex-1 flex-col gap-1 p-3">
        <p className="text-base font-bold text-brand">
          {formatPrice(listing.price, listing.currency)}
        </p>
        <h3 className="line-clamp-2 text-sm font-medium leading-snug text-neutral-800">
          {listing.title}
        </h3>
        <div className="mt-auto flex items-center justify-between pt-1 text-xs text-neutral-500">
          <span className="truncate">{listing.location || "—"}</span>
          <span className="shrink-0 capitalize">{listing.condition_display}</span>
        </div>
      </div>
    </Link>
  );
}

/** Loading placeholder matching the card's footprint. */
export function ListingCardSkeleton() {
  return (
    <div className="flex flex-col overflow-hidden rounded-2xl border border-neutral-200 bg-white">
      <div className="aspect-square animate-pulse bg-neutral-100" />
      <div className="space-y-2 p-3">
        <div className="h-4 w-1/2 animate-pulse rounded bg-neutral-200" />
        <div className="h-3 w-4/5 animate-pulse rounded bg-neutral-100" />
        <div className="h-3 w-2/3 animate-pulse rounded bg-neutral-100" />
      </div>
    </div>
  );
}
