"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ListingDetail } from "@/components/ListingDetail";
import { useAuth } from "@/lib/auth";
import type { Listing } from "@/lib/types";

/**
 * Renders a listing. Active listings arrive pre-fetched from the server. When
 * the server couldn't see it (a draft/reserved listing is private), we retry
 * client-side with the viewer's token — so an owner can open their own draft.
 */
export function ListingDetailLoader({
  id,
  initial,
}: {
  id: string;
  initial: Listing | null;
}) {
  const { authFetch, loading: authLoading } = useAuth();
  const [listing, setListing] = useState<Listing | null>(initial);
  const [state, setState] = useState<"ready" | "loading" | "missing">(
    initial ? "ready" : "loading",
  );

  useEffect(() => {
    if (initial || authLoading) return;
    let cancelled = false;
    (async () => {
      const res = await authFetch(`/api/v1/listings/${id}/`);
      if (cancelled) return;
      if (res.ok) {
        setListing((await res.json()) as Listing);
        setState("ready");
      } else {
        setState("missing");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, initial, authLoading, authFetch]);

  if (state === "loading") {
    return <main className="mx-auto max-w-3xl px-4 py-12 text-sm text-neutral-500">Loading…</main>;
  }

  if (state === "missing" || !listing) {
    return (
      <main className="mx-auto max-w-3xl space-y-3 px-4 py-16 text-center">
        <h1 className="text-xl font-bold">Listing not found</h1>
        <p className="text-sm text-neutral-500">
          It may have been removed or isn&apos;t public.
        </p>
        <Link href="/" className="inline-block text-sm font-medium text-brand hover:underline">
          ← Back to browse
        </Link>
      </main>
    );
  }

  return <ListingDetail listing={listing} />;
}
