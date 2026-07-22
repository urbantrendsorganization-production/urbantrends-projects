"use client";

import Link from "next/link";
import { useState } from "react";

import { useAuth } from "@/lib/auth";
import { PUBLIC_API_BASE } from "@/lib/config";

export function SiteHeader() {
  const { user, loading, isAuthenticated, logout } = useAuth();

  return (
    <>
      <header className="sticky top-0 z-10 border-b border-neutral-200 bg-white/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-3xl items-center justify-between px-4">
          <Link href="/" className="text-lg font-bold tracking-tight text-brand">
            Marketplace
          </Link>

          <nav className="flex items-center gap-4 text-sm">
            {loading ? null : isAuthenticated ? (
              <>
                <Link href="/profile" className="font-medium text-neutral-700 hover:text-brand">
                  {user?.display_name || "Profile"}
                </Link>
                <button
                  onClick={logout}
                  className="font-medium text-neutral-500 hover:text-neutral-900"
                >
                  Sign out
                </button>
              </>
            ) : (
              <>
                <Link href="/login" className="font-medium text-neutral-700 hover:text-brand">
                  Sign in
                </Link>
                <Link
                  href="/register"
                  className="rounded-lg bg-brand px-3 py-1.5 font-semibold text-white hover:bg-brand-dark"
                >
                  Register
                </Link>
              </>
            )}
          </nav>
        </div>
      </header>

      {isAuthenticated && user && !user.is_verified ? <VerifyBanner email={user.email} /> : null}
    </>
  );
}

function VerifyBanner({ email }: { email: string }) {
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  const resend = async () => {
    setBusy(true);
    try {
      await fetch(`${PUBLIC_API_BASE}/api/v1/auth/resend-verification/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      setSent(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="border-b border-amber-200 bg-amber-50">
      <div className="mx-auto flex max-w-3xl items-center justify-between gap-3 px-4 py-2 text-sm text-amber-800">
        <span>Your email isn&apos;t verified yet. Check your inbox to unlock posting.</span>
        {sent ? (
          <span className="font-medium">Sent ✓</span>
        ) : (
          <button
            onClick={resend}
            disabled={busy}
            className="whitespace-nowrap font-semibold underline disabled:opacity-50"
          >
            Resend link
          </button>
        )}
      </div>
    </div>
  );
}
