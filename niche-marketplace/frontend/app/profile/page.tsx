"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Alert, Button, Card, Field, TextInput } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export default function ProfilePage() {
  const { user, loading, authFetch, refreshUser } = useAuth();
  const router = useRouter();

  const [form, setForm] = useState({ display_name: "", location: "", phone: "" });
  const [avatar, setAvatar] = useState<File | null>(null);
  const [status, setStatus] = useState<{ tone: "success" | "error"; msg: string } | null>(null);
  const [busy, setBusy] = useState(false);

  // Redirect anonymous visitors to sign in.
  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  // Seed the form once the user loads.
  useEffect(() => {
    if (user) {
      setForm({
        display_name: user.display_name,
        location: user.location,
        phone: user.phone,
      });
    }
  }, [user]);

  if (loading || !user) {
    return <main className="mx-auto max-w-md px-4 py-12 text-sm text-neutral-500">Loading…</main>;
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setStatus(null);
    setBusy(true);
    try {
      const body = new FormData();
      body.append("display_name", form.display_name);
      body.append("location", form.location);
      body.append("phone", form.phone);
      if (avatar) body.append("avatar", avatar);

      const res = await authFetch("/api/v1/users/me/", { method: "PATCH", body });
      if (!res.ok) throw new Error("Could not save your profile.");
      await refreshUser();
      setAvatar(null);
      setStatus({ tone: "success", msg: "Profile saved." });
    } catch (err) {
      setStatus({ tone: "error", msg: err instanceof Error ? err.message : "Save failed." });
    } finally {
      setBusy(false);
    }
  };

  const joined = new Date(user.joined_at).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
  });

  return (
    <main className="mx-auto max-w-md space-y-6 px-4 py-12">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Your profile</h1>
        <Link href={`/users/${user.id}`} className="text-sm font-medium text-brand hover:underline">
          View public profile →
        </Link>
      </div>

      <Card>
        <div className="flex items-center justify-between gap-4 text-sm">
          <div>
            <div className="font-medium">{user.email}</div>
            <div className="text-neutral-500">Joined {joined}</div>
          </div>
          <span
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              user.is_verified ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"
            }`}
          >
            {user.is_verified ? "Verified" : "Unverified"}
          </span>
        </div>
      </Card>

      <Card>
        <form onSubmit={onSubmit} className="space-y-4">
          {status ? <Alert tone={status.tone}>{status.msg}</Alert> : null}

          <Field label="Display name">
            <TextInput
              value={form.display_name}
              onChange={(e) => setForm({ ...form, display_name: e.target.value })}
              placeholder="How you appear to others"
            />
          </Field>

          <Field label="Location">
            <TextInput
              value={form.location}
              onChange={(e) => setForm({ ...form, location: e.target.value })}
              placeholder="City, Country"
            />
          </Field>

          <Field label="Phone" hint="Private — never shown on your public profile.">
            <TextInput
              value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })}
              placeholder="+254…"
            />
          </Field>

          <Field label="Avatar">
            <input
              type="file"
              accept="image/*"
              onChange={(e) => setAvatar(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-neutral-500 file:mr-3 file:rounded-lg file:border-0 file:bg-neutral-100 file:px-3 file:py-2 file:text-sm file:font-medium hover:file:bg-neutral-200"
            />
          </Field>

          <Button type="submit" disabled={busy}>
            {busy ? "Saving…" : "Save changes"}
          </Button>
        </form>
      </Card>
    </main>
  );
}
