"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

type Health = {
  status: string;
  database?: string;
  message?: string;
};

type Session = {
  user_id: string;
  tenant_id: string;
  role: string;
};

async function fetchHealth(): Promise<Health> {
  try {
    const res = await fetch("/api/health", { cache: "no-store" });
    return (await res.json()) as Health;
  } catch (error) {
    return {
      status: "unreachable",
      message: error instanceof Error ? error.message : "unknown error",
    };
  }
}

async function fetchSession(): Promise<Session | null> {
  try {
    const res = await fetch("/api/me", { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as Session;
  } catch {
    return null;
  }
}

export default function Home() {
  const router = useRouter();
  const [health, setHealth] = useState<Health | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    Promise.all([fetchHealth(), fetchSession()])
      .then(([h, s]) => {
        if (!active) return;
        setHealth(h);
        setSession(s);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    setSession(null);
    router.push("/login");
  }

  const healthy = health?.status === "ok";

  return (
    <main className="flex min-h-screen items-center justify-center bg-muted/30 p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            OnboardKit — Office
            <Badge variant={healthy ? "default" : "destructive"}>
              {loading ? "checking…" : (health?.status ?? "unknown")}
            </Badge>
          </CardTitle>
          <CardDescription>Reviewer &amp; admin console</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <dl className="grid grid-cols-2 gap-2 text-sm">
            <dt className="text-muted-foreground">API status</dt>
            <dd className="text-right font-medium">
              {loading ? "…" : (health?.status ?? "unknown")}
            </dd>
            <dt className="text-muted-foreground">Database</dt>
            <dd className="text-right font-medium">
              {loading ? "…" : (health?.database ?? "unknown")}
            </dd>
            <dt className="text-muted-foreground">Session</dt>
            <dd className="text-right font-medium">
              {loading ? "…" : session ? `${session.role}` : "signed out"}
            </dd>
          </dl>
          {health?.message ? (
            <p className="text-sm text-destructive">{health.message}</p>
          ) : null}
          {loading ? null : session ? (
            <Button onClick={logout} variant="outline" className="w-full">
              Sign out
            </Button>
          ) : (
            <Link href="/login" className={cn(buttonVariants(), "w-full")}>
              Sign in
            </Link>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
