"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ImagePicker } from "@/components/ImagePicker";
import { ListingForm, type ListingFormValues } from "@/components/ListingForm";
import { Alert, Card, Field } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { fetchCategories } from "@/lib/catalog";
import { apiError } from "@/lib/errors";
import type { Category } from "@/lib/types";

export default function SellPage() {
  const { user, loading, authFetch } = useAuth();
  const router = useRouter();

  const [categories, setCategories] = useState<Category[]>([]);
  const [images, setImages] = useState<File[]>([]);
  const [publish, setPublish] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    fetchCategories().then(setCategories);
  }, []);

  if (loading || !user) {
    return <main className="mx-auto max-w-lg px-4 py-12 text-sm text-neutral-500">Loading…</main>;
  }

  if (!user.is_verified) {
    return (
      <main className="mx-auto max-w-lg space-y-4 px-4 py-12">
        <h1 className="text-2xl font-bold tracking-tight">Post a listing</h1>
        <Alert tone="info">
          Verify your email before posting. Check your inbox for the link (in development
          it&apos;s printed to the backend console).
        </Alert>
      </main>
    );
  }

  const onSubmit = async (values: ListingFormValues) => {
    setError(null);
    setBusy(true);
    try {
      // 1. Create the draft listing.
      const res = await authFetch("/api/v1/listings/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(apiError(data, "Could not create the listing."));
      const id = data.id as number;

      // 2. Upload images (best-effort — the listing already exists).
      if (images.length) {
        const body = new FormData();
        images.forEach((f) => body.append("images", f));
        await authFetch(`/api/v1/listings/${id}/images/`, { method: "POST", body });
      }

      // 3. Optionally publish immediately.
      if (publish) {
        await authFetch(`/api/v1/listings/${id}/transition/`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: "active" }),
        });
      }

      router.push(`/listings/${id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the listing.");
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto max-w-lg space-y-6 px-4 py-12">
      <h1 className="text-2xl font-bold tracking-tight">Post a listing</h1>

      <Card>
        {error ? (
          <div className="mb-4">
            <Alert tone="error">{error}</Alert>
          </div>
        ) : null}

        <ListingForm
          categories={categories}
          submitLabel={publish ? "Publish listing" : "Save draft"}
          submitting={busy}
          onSubmit={onSubmit}
        >
          <Field label="Photos">
            <ImagePicker files={images} onChange={setImages} />
          </Field>

          <label className="flex items-center gap-2 text-sm text-neutral-700">
            <input
              type="checkbox"
              checked={publish}
              onChange={(e) => setPublish(e.target.checked)}
              className="h-4 w-4 rounded border-neutral-300 text-brand focus:ring-brand"
            />
            Publish immediately (uncheck to save as a draft)
          </label>
        </ListingForm>
      </Card>
    </main>
  );
}
