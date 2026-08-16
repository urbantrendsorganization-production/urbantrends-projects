"use client";

/**
 * `/staff` — boots into Today from one `/me/` call.
 *
 * `/me/` returns `chairs`: the shops where this person is bookable. One chair
 * goes straight through, which is the case for every stylist. More than one is
 * a working owner or a stylist who covers two branches, and they pick — a
 * chooser that appears only when it is needed.
 *
 * A manager with no chair anywhere still gets Today for a shop they manage;
 * scope resolution is the server's, not this file's — see `scheduling/views.py`.
 */

import { useEffect, useState } from "react";

import { Today } from "../../components/staff/Today";
import { ApiError, api } from "../../lib/api";
import { Button } from "../../components/staff/primitives";

type Chair = {
  staff_id: string;
  display_name: string;
  shop_id: string;
  shop_name: string;
  organization_id: string;
};

export default function StaffHome() {
  const [chairs, setChairs] = useState<Chair[] | null>(null);
  const [chosen, setChosen] = useState<Chair | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get("/api/v1/auth/me/")
      .then((data) => {
        setChairs(data.chairs);
        if (data.chairs.length === 1) setChosen(data.chairs[0]);
      })
      // Not signed in is not an error to display — it is a destination. Both
      // dashboards said "Sign in to see your dashboard" from the day they
      // shipped, with nowhere to do it, because `/signin` did not exist until
      // slice 11. A 401 or 403 here means the session is gone or was never
      // there, and the honest response is the front door.
      .catch((caught) => {
        if (caught instanceof ApiError && (caught.status === 401 || caught.status === 403)) {
          window.location.assign("/signin");
          return;
        }
        setError("Could not reach the shop. Check your connection.");
      });
  }, []);

  if (error) return <Shell>{error}</Shell>;
  if (!chairs) return <Shell>Loading…</Shell>;
  if (!chairs.length) return <Shell>You do not have a chair at any shop yet.</Shell>;

  if (!chosen) {
    return (
      <Shell>
        <div style={{ display: "grid", gap: "var(--bn-space-5)", width: "100%" }}>
          {chairs.map((chair) => (
            <Button key={chair.staff_id} variant="secondary" onClick={() => setChosen(chair)}>
              {chair.shop_name}
            </Button>
          ))}
        </div>
      </Shell>
    );
  }

  return <Today orgId={chosen.organization_id} shopId={chosen.shop_id} />;
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main
      style={{
        maxWidth: 480,
        margin: "0 auto",
        padding: "var(--bn-space-12) var(--bn-space-gutter)",
        display: "flex",
        justifyContent: "center",
        color: "var(--bn-ink-45)",
      }}
    >
      {children}
    </main>
  );
}
