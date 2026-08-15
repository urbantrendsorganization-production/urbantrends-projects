"use client";

/**
 * `/signup` — one form, and at the end of it a shop owner has an organization.
 *
 * `POST /api/v1/signup/` creates the `User`, the `Organization` and the owner
 * `Membership` in a single transaction and logs the person in, so there is no
 * half-made account to clean up if the second write fails.
 *
 * ## Four fields, and why not fewer
 *
 * The organization's name is asked for because it is the name that ends up on
 * the client's booking page and in the SMS they receive. Deriving it from
 * anything else — the owner's name, the phone number — produces "Wanjiku
 * Mwangi" on a client's confirmation for a shop called Mint Braids.
 *
 * Email is optional and not asked for at all. CLAUDE.md §12: phone is the
 * `USERNAME_FIELD` precisely because salon staff often have no working email,
 * and an optional field on a signup form is a field that costs a second of
 * hesitation for nothing.
 *
 * ## Password rules come from the server
 *
 * `SignupSerializer` runs Django's validators, so the message a person reads
 * about their password is the one that will actually be enforced. Restating
 * "at least 8 characters" here would be a second copy of a rule that is set in
 * `AUTH_PASSWORD_VALIDATORS`, and the two would drift.
 */

import { useState } from "react";

import {
  AuthShell,
  ErrorPanel,
  Field,
  PhoneInput,
  TextInput,
  toE164,
} from "../../components/auth/fields";
import { Button } from "../../components/staff/primitives";
import { ApiError, api } from "../../lib/api";
import { firstError } from "../../lib/auth";

export default function SignUpPage() {
  const [organization, setOrganization] = useState("");
  const [fullName, setFullName] = useState("");
  const [local, setLocal] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const ready =
    organization.trim().length > 1 && fullName.trim().length > 1 && local.length === 9 && !!password;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/v1/signup/", {
        organization_name: organization.trim(),
        full_name: fullName.trim(),
        phone: toE164(local),
        password,
      });
      // Signed in already — the endpoint calls `login()`. Straight to the
      // dashboard, which knows how to be empty: slice 9 made a shopless
      // organization an empty report rather than a 404, precisely for this
      // moment.
      window.location.assign("/owner");
    } catch (caught) {
      setError(
        firstError(
          caught instanceof ApiError ? caught.body : null,
          "Could not create the account. Check your connection and try again.",
        ),
      );
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title="Create your shop"
      intro="One account for the whole business, however many branches you run."
      footer={
        <>
          Already have an account? <a href="/signin">Sign in</a>.
        </>
      }
    >
      <form
        style={{ display: "grid", gap: "var(--bn-space-7)" }}
        onSubmit={(event) => {
          event.preventDefault();
          if (ready && !busy) void submit();
        }}
      >
        <ErrorPanel>{error}</ErrorPanel>

        <Field label="Business name" hint="What clients will see on your booking page.">
          <TextInput
            value={organization}
            onChange={setOrganization}
            placeholder="Mint Braids"
            autoComplete="organization"
          />
        </Field>

        <Field label="Your name">
          <TextInput
            value={fullName}
            onChange={setFullName}
            placeholder="Wanjiku Mwangi"
            autoComplete="name"
          />
        </Field>

        <Field label="Phone number" hint="This is how you will sign in.">
          <PhoneInput value={local} onChange={setLocal} autoComplete="username" />
        </Field>

        <Field label="Password">
          <TextInput
            type="password"
            value={password}
            onChange={setPassword}
            autoComplete="new-password"
          />
        </Field>

        <Button
          onClick={() => void submit()}
          disabled={!ready || busy}
          disabledReason={busy ? "Creating your account…" : "Fill in all four to continue"}
        >
          Create account
        </Button>
      </form>
    </AuthShell>
  );
}
