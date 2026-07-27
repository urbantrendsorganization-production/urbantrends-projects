"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ImagePicker } from "@/components/ImagePicker";
import { ListingForm, type ListingFormValues } from "@/components/ListingForm";
import { Alert, Button, Card, Field } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { fetchCategories } from "@/lib/catalog";
import { apiError } from "@/lib/errors";
import type { Category, Listing } from "@/lib/types";

export default function EditListingPage() {
  const { id } = useParams<{ id: string }>();
  const { user, loading, authFetch } = useAuth();
  const router = useRouter();

  const [categories, setCategories] = useState<Category[]>([]);
  const [listing, setListing] = useState<Listing | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "denied">("loading");
  const [newImages, setNewImages] = useState<File[]>([]);
  const [status, setStatus] = useState<{ tone: "success" | "error"; msg: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const res = await authFetch(`/api/v1/listings/${id}/`);
    if (!res.ok) return setState("denied");
    const data = (await res.json()) as Listing;
    setListing(data);
    setState("ready");
  }, [authFetch, id]);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    fetchCategories().then(setCategories);
  }, []);

  useEffect(() => {
    if (!loading && user) load();
  }, [loading, user, load]);

  if (loading || state === "loading") {
    return <main className="mx-auto max-w-lg px-4 py-12 text-sm text-neutral-500">Loading…</main>;
  }

  if (state === "denied" || !listing || (user && user.id !== listing.seller.id)) {
    return (
      <main className="mx-auto max-w-lg space-y-3 px-4 py-16 text-center">
        <h1 className="text-xl font-bold">Can&apos;t edit this listing</h1>
        <Link href="/my-listings" className="text-sm font-medium text-brand hover:underline">
          ← Back to your listings
        </Link>
      </main>
    );
  }

  const initial: ListingFormValues = {
    category: listing.category.id,
    title: listing.title,
    description: listing.description,
    price: listing.price,
    currency: listing.currency,
    condition: listing.condition,
    location: listing.location,
    attributes: listing.attributes,
  };

  const onSubmit = async (values: ListingFormValues) => {
    setStatus(null);
    setBusy(true);
    try {
      const res = await authFetch(`/api/v1/listings/${id}/`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(apiError(data, "Could not save changes."));
      setListing(data as Listing);
      setStatus({ tone: "success", msg: "Changes saved." });
    } catch (err) {
      setStatus({ tone: "error", msg: err instanceof Error ? err.message : "Save failed." });
    } finally {
      setBusy(false);
    }
  };

  const uploadImages = async () => {
    if (!newImages.length) return;
    setBusy(true);
    const body = new FormData();
    newImages.forEach((f) => body.append("images", f));
    const res = await authFetch(`/api/v1/listings/${id}/images/`, { method: "POST", body });
    setBusy(false);
    if (res.ok) {
      setNewImages([]);
      await load();
    } else {
      setStatus({ tone: "error", msg: "Image upload failed." });
    }
  };

  const removeImage = async (imageId: number) => {
    const res = await authFetch(`/api/v1/listings/${id}/images/${imageId}/`, {
      method: "DELETE",
    });
    if (res.ok) await load();
  };

  return (
    <main className="mx-auto max-w-lg space-y-6 px-4 py-12">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Edit listing</h1>
        <Link href={`/listings/${id}`} className="text-sm font-medium text-brand hover:underline">
          View →
        </Link>
      </div>

      <Card>
        <div className="space-y-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">Photos</h2>
          {listing.images.length ? (
            <div className="grid grid-cols-4 gap-2">
              {listing.images.map((img) => (
                <div key={img.id} className="group relative aspect-square">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={img.thumbnail ?? img.image}
                    alt=""
                    className="h-full w-full rounded-lg object-cover"
                  />
                  <button
                    type="button"
                    onClick={() => removeImage(img.id)}
                    className="absolute right-1 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-black/60 text-xs text-white opacity-0 transition group-hover:opacity-100"
                    aria-label="Remove image"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-neutral-400">No photos yet.</p>
          )}

          <ImagePicker files={newImages} onChange={setNewImages} />
          {newImages.length ? (
            <Button type="button" onClick={uploadImages} disabled={busy}>
              {busy ? "Uploading…" : `Upload ${newImages.length} photo(s)`}
            </Button>
          ) : null}
        </div>
      </Card>

      <Card>
        {status ? (
          <div className="mb-4">
            <Alert tone={status.tone}>{status.msg}</Alert>
          </div>
        ) : null}
        <ListingForm
          categories={categories}
          initial={initial}
          submitLabel="Save changes"
          submitting={busy}
          onSubmit={onSubmit}
        />
      </Card>
    </main>
  );
}
