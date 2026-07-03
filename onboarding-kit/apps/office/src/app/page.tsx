"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

type Health = {
  status: string;
  database?: string;
  message?: string;
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

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    // State is only set after the await resolves — never synchronously in the
    // effect body (react-hooks/set-state-in-effect).
    fetchHealth()
      .then((result) => {
        if (active) setHealth(result);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const refresh = () => {
    setLoading(true);
    fetchHealth()
      .then(setHealth)
      .finally(() => setLoading(false));
  };

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
          </dl>
          {health?.message ? (
            <p className="text-sm text-destructive">{health.message}</p>
          ) : null}
          <Button onClick={refresh} disabled={loading} className="w-full">
            Refresh
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}
