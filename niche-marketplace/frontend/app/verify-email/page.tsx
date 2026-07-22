"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import { Alert, Card, TextLink } from "@/components/ui";
import { PUBLIC_API_BASE } from "@/lib/config";

type Status = "pending" | "success" | "error";

function VerifyInner() {
  const params = useSearchParams();
  const token = params.get("token");
  const [status, setStatus] = useState<Status>("pending");
  const [message, setMessage] = useState("Verifying your email…");
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return; // guard React 18 strict-mode double-invoke
    ran.current = true;

    if (!token) {
      setStatus("error");
      setMessage("This link is missing its verification token.");
      return;
    }

    (async () => {
      try {
        const res = await fetch(`${PUBLIC_API_BASE}/api/v1/auth/verify-email/`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token }),
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok) {
          setStatus("success");
          setMessage(data.detail ?? "Email verified.");
        } else {
          setStatus("error");
          setMessage(data.detail ?? "This verification link is invalid or expired.");
        }
      } catch {
        setStatus("error");
        setMessage("Couldn't reach the server. Please try again.");
      }
    })();
  }, [token]);

  return (
    <Card>
      <div className="space-y-4">
        {status === "pending" ? (
          <p className="text-sm text-neutral-500">{message}</p>
        ) : (
          <Alert tone={status === "success" ? "success" : "error"}>{message}</Alert>
        )}

        {status === "success" ? (
          <p className="text-sm">
            <TextLink href="/login">Continue to sign in →</TextLink>
          </p>
        ) : null}
        {status === "error" ? (
          <p className="text-sm text-neutral-500">
            Need a new link? Sign in and use the “Resend link” banner, or{" "}
            <TextLink href="/register">register again</TextLink>.
          </p>
        ) : null}
      </div>
    </Card>
  );
}

export default function VerifyEmailPage() {
  return (
    <main className="mx-auto max-w-md px-4 py-12">
      <h1 className="mb-6 text-2xl font-bold tracking-tight">Email verification</h1>
      <Suspense fallback={<Card>Loading…</Card>}>
        <VerifyInner />
      </Suspense>
    </main>
  );
}
