"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert, Button, StatusBadge } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { formatPrice } from "@/lib/catalog";
import { apiError } from "@/lib/errors";
import type { Listing, ListingStatus } from "@/lib/types";

export function ListingDetail({ listing: initial }: { listing: Listing }) {
  const [listing, setListing] = useState(initial);
  const [active, setActive] = useState(0);
  const images = listing.images;

  const joined = new Date(listing.created_at).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });

  return (
    <main className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <div className="flex items-center gap-3">
        <Link href="/" className="text-sm text-neutral-500 hover:text-brand">
          ← Browse
        </Link>
        <StatusBadge status={listing.status} />
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <div className="space-y-2">
          <div className="aspect-square overflow-hidden rounded-2xl border border-neutral-200 bg-neutral-100">
            {images.length ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={images[active].image}
                alt={listing.title}
                className="h-full w-full object-cover"
              />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-neutral-400">
                No photos
              </div>
            )}
          </div>
          {images.length > 1 ? (
            <div className="grid grid-cols-5 gap-2">
              {images.map((img, i) => (
                <button
                  key={img.id}
                  onClick={() => setActive(i)}
                  className={`aspect-square overflow-hidden rounded-lg border-2 ${
                    i === active ? "border-brand" : "border-transparent"
                  }`}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={img.thumbnail ?? img.image}
                    alt=""
                    className="h-full w-full object-cover"
                  />
                </button>
              ))}
            </div>
          ) : null}
        </div>

        <div className="space-y-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{listing.title}</h1>
            <p className="mt-1 text-2xl font-bold text-brand">
              {formatPrice(listing.price, listing.currency)}
            </p>
          </div>

          <dl className="grid grid-cols-2 gap-y-2 text-sm">
            <dt className="text-neutral-500">Condition</dt>
            <dd className="text-right font-medium">{listing.condition_display}</dd>
            {listing.location ? (
              <>
                <dt className="text-neutral-500">Location</dt>
                <dd className="text-right font-medium">{listing.location}</dd>
              </>
            ) : null}
            <dt className="text-neutral-500">Category</dt>
            <dd className="text-right font-medium">{listing.category.name}</dd>
            <dt className="text-neutral-500">Listed</dt>
            <dd className="text-right font-medium">{joined}</dd>
          </dl>

          <Link
            href={`/users/${listing.seller.id}`}
            className="flex items-center gap-3 rounded-xl border border-neutral-200 p-3 hover:bg-neutral-50"
          >
            {listing.seller.avatar ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={listing.seller.avatar}
                alt={listing.seller.name}
                className="h-10 w-10 rounded-full object-cover"
              />
            ) : (
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-brand text-sm font-bold text-white">
                {listing.seller.name.charAt(0).toUpperCase()}
              </div>
            )}
            <div className="text-sm">
              <div className="font-medium">{listing.seller.name}</div>
              <div className="text-neutral-500">View profile →</div>
            </div>
          </Link>

          <MessageSellerButton listing={listing} />
        </div>
      </div>

      {listing.description ? (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
            Description
          </h2>
          <p className="whitespace-pre-line text-sm text-neutral-700">{listing.description}</p>
        </section>
      ) : null}

      {Object.keys(listing.attributes).length ? (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
            Details
          </h2>
          <dl className="grid grid-cols-2 gap-y-2 rounded-xl border border-neutral-200 p-4 text-sm sm:grid-cols-3">
            {listing.category.attribute_schema.map((field) => {
              const value = listing.attributes[field.key];
              if (value === undefined) return null;
              return (
                <div key={field.key}>
                  <dt className="text-neutral-500">{field.label}</dt>
                  <dd className="font-medium">
                    {typeof value === "boolean" ? (value ? "Yes" : "No") : String(value)}
                  </dd>
                </div>
              );
            })}
          </dl>
        </section>
      ) : null}

      <OwnerActions listing={listing} onChange={setListing} />
    </main>
  );
}

function MessageSellerButton({ listing }: { listing: Listing }) {
  const { user, isAuthenticated, authFetch } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The owner manages the listing elsewhere; no "message yourself" button.
  if (user && user.id === listing.seller.id) return null;
  // Sold/inactive listings aren't message-worthy from the public page.
  if (listing.status !== "active" && listing.status !== "reserved") return null;

  if (!isAuthenticated) {
    return (
      <Link
        href={`/login?next=/listings/${listing.id}`}
        className="flex h-11 w-full items-center justify-center rounded-xl bg-brand text-sm font-semibold text-white transition hover:bg-brand-dark"
      >
        Sign in to message seller
      </Link>
    );
  }

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await authFetch("/api/v1/conversations/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ listing: listing.id }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(apiError(data, "Couldn't start the conversation."));
      router.push(`/messages/${data.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2">
      <Button onClick={start} disabled={busy} className="w-full">
        {busy ? "Opening…" : "Message seller"}
      </Button>
      {error ? <Alert tone="error">{error}</Alert> : null}
    </div>
  );
}

// Status -> the transitions a seller can trigger from the detail page.
const ACTIONS: Record<ListingStatus, { label: string; to: ListingStatus }[]> = {
  draft: [{ label: "Publish", to: "active" }],
  active: [
    { label: "Mark reserved", to: "reserved" },
    { label: "Mark sold", to: "sold" },
  ],
  reserved: [
    { label: "Mark sold", to: "sold" },
    { label: "Re-activate", to: "active" },
  ],
  expired: [{ label: "Re-activate", to: "active" }],
  sold: [],
};

function OwnerActions({
  listing,
  onChange,
}: {
  listing: Listing;
  onChange: (listing: Listing) => void;
}) {
  const { user, authFetch } = useAuth();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!user || user.id !== listing.seller.id) return null;

  const transition = async (to: ListingStatus) => {
    setError(null);
    setBusy(true);
    try {
      const res = await authFetch(`/api/v1/listings/${listing.id}/transition/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: to }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(apiError(data, "Could not update the listing."));
      onChange(data as Listing);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update the listing.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!confirm("Delete this listing? This can't be undone.")) return;
    setBusy(true);
    const res = await authFetch(`/api/v1/listings/${listing.id}/`, { method: "DELETE" });
    if (res.ok) router.push("/my-listings");
    else setBusy(false);
  };

  return (
    <section className="space-y-3 rounded-2xl border border-neutral-200 bg-neutral-50 p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
        Manage listing
      </h2>
      {error ? <Alert tone="error">{error}</Alert> : null}
      <div className="flex flex-wrap gap-2">
        <Link
          href={`/listings/${listing.id}/edit`}
          className="inline-flex h-11 items-center justify-center rounded-xl border border-neutral-300 bg-white px-5 text-sm font-semibold text-neutral-700 transition hover:bg-neutral-100"
        >
          Edit
        </Link>
        {ACTIONS[listing.status].map((a) => (
          <Button key={a.to} onClick={() => transition(a.to)} disabled={busy}>
            {a.label}
          </Button>
        ))}
        <button
          onClick={remove}
          disabled={busy}
          className="inline-flex h-11 items-center justify-center rounded-xl border border-red-200 bg-white px-5 text-sm font-semibold text-red-600 transition hover:bg-red-50 disabled:opacity-50"
        >
          Delete
        </button>
      </div>
    </section>
  );
}
