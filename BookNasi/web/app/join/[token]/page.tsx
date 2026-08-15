"use client";

/**
 * `/join/<token>` — a stylist turning an SMS into an account.
 *
 * Unauthenticated on purpose, and that is not a gap. The invitee has no account
 * yet; that is the whole reason `StaffInvite` exists separately from
 * `Membership`, and why the owner can put somebody on the rota before they have
 * ever signed in. The design draws that state on the staff list as "Invited
 * 3 Aug · hasn't signed in yet".
 *
 * ## The phone number is not asked for
 *
 * It is already on the invite. Asking would let somebody who intercepted the
 * link attach it to a different number, and would mean a stylist whose SMS went
 * to their work phone could accept it onto their personal one — quietly
 * breaking the per-person attribution the owner dashboard is built on
 * (CLAUDE.md §12).
 *
 * ## One refusal for every kind of bad token
 *
 * Missing, expired, revoked and already-accepted all answer the same sentence,
 * from the server. Telling them apart would tell a token-guesser which guesses
 * were warm. This screen renders what it is given.
 *
 * ## An existing account keeps its password
 *
 * `InviteAcceptView` will attach the membership to a `User` that already exists
 * on that number — a stylist who works at two shops in one organization is one
 * person — and it deliberately does not overwrite their password, so an invite
 * cannot be used as a password reset. The field below is therefore "choose a
 * password" for a new person and ignored for a returning one, which is why it
 * does not promise to change anything.
 */

import { use, useState } from "react";

import { AuthShell, ErrorPanel, Field, TextInput } from "../../../components/auth/fields";
import { Button } from "../../../components/staff/primitives";
import { ApiError, api } from "../../../lib/api";
import { firstError } from "../../../lib/auth";

export default function JoinPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const ready = fullName.trim().length > 1 && password.length > 0;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/v1/auth/invite/accept/", {
        token,
        full_name: fullName.trim(),
        password,
      });
      // The endpoint signs them in. Their own day is the only screen they have
      // — CLAUDE.md §12: staff see only their own day.
      window.location.assign("/staff");
    } catch (caught) {
      setError(
        firstError(
          caught instanceof ApiError ? caught.body : null,
          "Could not accept the invite. Check your connection and try again.",
        ),
      );
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title="Join your shop"
      intro="Set a password and you are on the rota. No app to install."
      footer="Your phone number came with the invite — you will sign in with it from now on."
    >
      <form
        style={{ display: "grid", gap: "var(--bn-space-7)" }}
        onSubmit={(event) => {
          event.preventDefault();
          if (ready && !busy) void submit();
        }}
      >
        <ErrorPanel>{error}</ErrorPanel>

        <Field label="Your name" hint="What clients see when they book with you.">
          <TextInput
            value={fullName}
            onChange={setFullName}
            placeholder="Grace Otieno"
            autoComplete="name"
          />
        </Field>

        <Field label="Choose a password">
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
          disabledReason={busy ? "Setting up…" : "Add your name and a password"}
        >
          Join
        </Button>
      </form>
    </AuthShell>
  );
}
