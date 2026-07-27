"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { StatusBadge } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { formatPrice } from "@/lib/catalog";
import type { Listing, ListingStatus, Paginated } from "@/lib/types";

// One quick primary action per status, straight from the dashboard.
const QUICK: Partial<Record<ListingStatus, { label: string; to: ListingStatus }>> = {
  draft: { label: "Publish", to: "active" },
  active: { label: "Mark sold", to: "sold" },
  reserved: { label: "Mark sold", to: "sold" },
  expired: { label: "Re-activate", to: "active" },
};

export default function MyListingsPage() {
  const { user, loading, authFetch } = useAuth();
  const router = useRouter();

  const [listings, setListings] = useState<Listing[]>([]);
  const [ready, setReady] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    const res = await authFetch("/api/v1/listings/mine/?limit=100");
    if (res.ok) {
      const data = (await res.json()) as Paginated<Listing>;
      setListings(data.results);
    }
    setReady(true);
  }, [authFetch]);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (!loading && user) load();
  }, [loading, user, load]);

  const quickAction = async (listing: Listing, to: ListingStatus) => {
    setBusyId(listing.id);
    const res = await authFetch(`/api/v1/listings/${listing.id}/transition/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: to }),
    });
    if (res.ok) await load();
    setBusyId(null);
  };

  if (loading || !user || !ready) {
    return <main className="mx-auto max-w-3xl px-4 py-12 text-sm text-neutral-500">Loading…</main>;
  }

  return (
    <main className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Your listings</h1>
        <Link
          href="/sell"
          className="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark"
        >
          Post a listing
        </Link>
      </div>

      {listings.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-neutral-300 py-16 text-center">
          <p className="text-sm text-neutral-500">You haven&apos;t posted anything yet.</p>
          <Link href="/sell" className="mt-2 inline-block text-sm font-medium text-brand hover:underline">
            Post your first listing →
          </Link>
        </div>
      ) : (
        <ul className="space-y-3">
          {listings.map((listing) => {
            const quick = QUICK[listing.status];
            const thumb = listing.images[0]?.thumbnail ?? listing.images[0]?.image;
            return (
              <li
                key={listing.id}
                className="flex items-center gap-4 rounded-2xl border border-neutral-200 bg-white p-3"
              >
                <Link
                  href={`/listings/${listing.id}`}
                  className="h-16 w-16 flex-shrink-0 overflow-hidden rounded-xl bg-neutral-100"
                >
                  {thumb ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={thumb} alt="" className="h-full w-full object-cover" />
                  ) : (
                    <div className="flex h-full items-center justify-center text-xs text-neutral-400">
                      No photo
                    </div>
                  )}
                </Link>

                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Link
                      href={`/listings/${listing.id}`}
                      className="truncate font-medium hover:text-brand"
                    >
                      {listing.title}
                    </Link>
                    <StatusBadge status={listing.status} />
                  </div>
                  <p className="text-sm text-neutral-500">
                    {formatPrice(listing.price, listing.currency)}
                  </p>
                </div>

                <div className="flex flex-shrink-0 items-center gap-2">
                  {quick ? (
                    <button
                      onClick={() => quickAction(listing, quick.to)}
                      disabled={busyId === listing.id}
                      className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
                    >
                      {quick.label}
                    </button>
                  ) : null}
                  <Link
                    href={`/listings/${listing.id}/edit`}
                    className="rounded-lg border border-neutral-300 px-3 py-1.5 text-sm font-medium text-neutral-700 hover:bg-neutral-100"
                  >
                    Edit
                  </Link>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}
