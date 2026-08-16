"use client";

/**
 * `/signin` — the front door, which until slice 11 did not exist.
 *
 * `/owner` and `/staff` have both said "Sign in to see your dashboard" since
 * they shipped, and there was nowhere to do it: `POST /api/v1/auth/login/` had
 * been on the API since slice 1 and nothing called it.
 *
 * ## One message for both wrong number and wrong password
 *
 * That is the server's decision (`accounts/serializers.LoginSerializer`) and
 * this screen renders it rather than improving on it. Distinguishing the two
 * would turn this endpoint into a way to ask which phone numbers have accounts,
 * and every number in the system belongs to a named person at a named shop —
 * personal data under the Kenya DPA 2019 (CLAUDE.md §9).
 *
 * ## Where you land
 *
 * `landingFor` decides, from the same `/me/` the dashboards boot on. Owners and
 * managers get the dashboard; everyone else gets their own day. Nothing here
 * chooses based on what was typed.
 */

import { useEffect, useState } from "react";

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
import { fetchMe, firstError, landingFor } from "../../lib/auth";

export default function SignInPage() {
  const [local, setLocal] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Already signed in? Go where you were going. A sign-in form shown to
  // somebody who is signed in is a form they will fill in, fail, and blame.
  useEffect(() => {
    let cancelled = false;
    void fetchMe()
      .then((me) => {
        if (!cancelled) window.location.replace(landingFor(me));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const ready = local.length === 9 && password.length > 0;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/v1/auth/login/", { phone: toE164(local), password });
      const me = await fetchMe();
      window.location.assign(landingFor(me));
    } catch (caught) {
      setError(
        firstError(
          caught instanceof ApiError ? caught.body : null,
          "Could not sign in. Check your connection and try again.",
        ),
      );
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title="Sign in"
      intro="Your phone number is your username."
      footer={
        <>
          New shop? <a href="/signup">Create an account</a>. Invited by a shop? Use the link in
          your SMS.
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

        <Field label="Phone number">
          <PhoneInput value={local} onChange={setLocal} autoComplete="username" />
        </Field>

        <Field label="Password">
          <TextInput
            type="password"
            value={password}
            onChange={setPassword}
            autoComplete="current-password"
          />
        </Field>

        <Button
          onClick={() => void submit()}
          disabled={!ready || busy}
          // The design's rule: a disabled button's label says why.
          disabledReason={busy ? "Signing in…" : "Enter your number and password"}
        >
          Sign in
        </Button>
      </form>
    </AuthShell>
  );
}
