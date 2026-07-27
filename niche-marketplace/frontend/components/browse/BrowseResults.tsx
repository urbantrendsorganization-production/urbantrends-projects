"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui";
import { fetchNextListings } from "@/lib/browse";
import type { Listing } from "@/lib/types";

import { ListingCard } from "./ListingCard";

/**
 * The listings grid. Seeded with the server-rendered first page, then grows by
 * following the cursor client-side. Keyed by ``queryKey`` in the parent so a
 * filter change remounts it fresh.
 */
export function BrowseResults({
  initial,
  initialCursor,
  query,
}: {
  initial: Listing[];
  initialCursor: string | null;
  query: string;
}) {
  const [items, setItems] = useState(initial);
  const [cursor, setCursor] = useState(initialCursor);
  const [loading, setLoading] = useState(false);

  // Keep state in sync if the server sends a new first page for the same key.
  useEffect(() => {
    setItems(initial);
    setCursor(initialCursor);
  }, [initial, initialCursor]);

  const loadMore = async () => {
    if (!cursor || loading) return;
    setLoading(true);
    const page = await fetchNextListings(new URLSearchParams(query), cursor);
    setItems((prev) => [...prev, ...page.results]);
    setCursor(page.nextCursor);
    setLoading(false);
  };

  if (items.length === 0) return <EmptyState />;

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-4">
        {items.map((listing) => (
          <ListingCard key={listing.id} listing={listing} />
        ))}
      </div>

      {cursor ? (
        <div className="flex justify-center">
          <Button onClick={loadMore} disabled={loading} className="min-w-44">
            {loading ? "Loading…" : "Load more"}
          </Button>
        </div>
      ) : (
        <p className="pb-4 text-center text-sm text-neutral-400">
          You&apos;ve reached the end.
        </p>
      )}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-neutral-300 bg-white py-20 text-center">
      <div className="text-4xl">🔍</div>
      <h3 className="mt-3 text-base font-semibold text-neutral-800">
        No listings match
      </h3>
      <p className="mt-1 max-w-xs text-sm text-neutral-500">
        Try widening your price range, clearing a filter, or searching for
        something else.
      </p>
    </div>
  );
}
