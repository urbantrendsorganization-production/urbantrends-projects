"use client";

/**
 * `/book/<shop-slug>` — the standalone booking page.
 *
 * Thin on purpose. It builds a transport, builds a flow, and hands it to the
 * screens. Everything about *the flow* lives in `@booknasi/booking-core`, so
 * slice 10's widget is this file again with a different mount and a different
 * transport — not a second implementation of the booking machine.
 *
 * In production this is reached as `shopname.booknasi.co.ke`, rewritten to this
 * route by Caddy. The slug is the shop's public identity and the only scope on
 * the whole surface; there is no login here and nothing to authenticate.
 */

import { use, useMemo } from "react";

import { createBookingFlow, httpTransport } from "@booknasi/booking-core";

import { BookingScreens } from "../../../components/booking/BookingFlow";
import { API_BASE } from "../../../lib/api";

export default function BookingPage({ params }: { params: Promise<{ slug: string }> }) {
  // Next 15 hands route params as a promise. Unwrapped once here rather than
  // threaded through the flow, which knows nothing about routing.
  const { slug } = use(params);
  const flow = useMemo(
    () =>
      createBookingFlow({
        slug,
        transport: httpTransport({
          baseUrl: API_BASE,
          // Injected rather than reached for, so booking-core stays free of
          // globals and the widget can supply the host's own client.
          fetchImpl: (url, init) => fetch(url, init),
          csrfToken: () =>
            document.cookie.match(/(^| )csrftoken=([^;]+)/)?.[2] ?? "",
        }),
      }),
    [slug]
  );

  return <BookingScreens flow={flow} />;
}
