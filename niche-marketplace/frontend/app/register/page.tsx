"use client";

import { useState } from "react";

import { Alert, Button, Card, Field, TextInput, TextLink } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export default function RegisterPage() {
  const { register } = useAuth();
  const [form, setForm] = useState({ email: "", password: "", display_name: "" });
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await register(form);
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto max-w-md px-4 py-12">
      <h1 className="mb-6 text-2xl font-bold tracking-tight">Create your account</h1>

      <Card>
        {done ? (
          <div className="space-y-4">
            <Alert tone="success">
              Almost there — we sent a verification link to{" "}
              <strong>{form.email}</strong>. Open it to activate your account.
            </Alert>
            <p className="text-sm text-neutral-500">
              In development the link is printed to the backend console.
            </p>
            <p className="text-sm">
              Already verified? <TextLink href="/login">Sign in</TextLink>
            </p>
          </div>
        ) : (
          <form onSubmit={onSubmit} className="space-y-4">
            {error ? <Alert tone="error">{error}</Alert> : null}

            <Field label="Display name">
              <TextInput
                value={form.display_name}
                onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                placeholder="Jane Doe"
                autoComplete="name"
              />
            </Field>

            <Field label="Email">
              <TextInput
                type="email"
                required
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="you@example.com"
                autoComplete="email"
              />
            </Field>

            <Field label="Password" hint="At least 8 characters.">
              <TextInput
                type="password"
                required
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                autoComplete="new-password"
              />
            </Field>

            <Button type="submit" disabled={busy} className="w-full">
              {busy ? "Creating…" : "Create account"}
            </Button>

            <p className="text-center text-sm text-neutral-500">
              Already have an account? <TextLink href="/login">Sign in</TextLink>
            </p>
          </form>
        )}
      </Card>
    </main>
  );
}
