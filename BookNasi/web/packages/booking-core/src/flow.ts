/**
 * The store. Holds the state, drives the transport, tells subscribers.
 *
 * A plain observable rather than a React hook, a signal or a context: those are
 * three framework choices and this package is allowed none of them. A renderer
 * binds with whatever it has — `useSyncExternalStore` in React, an effect in
 * Svelte, a manual re-render in the widget.
 *
 * ## Errors are classified here, not in the UI
 *
 * The hold endpoint answers 409 for a slot that went, 429 for a number holding
 * too much, and 400 for a request that was wrong. Those need three different
 * sentences and, more importantly, three different *next moves*: re-pick a
 * time, wait, or fix the number. Classifying them in a component would mean
 * classifying them again in the widget.
 *
 * ## The clock
 *
 * `now` is injected, exactly as it is in the availability engine, so a test can
 * expire a hold without waiting three minutes. The countdown itself is driven
 * by whatever renders it calling `tick()`; this package owns no timers, because
 * a timer is a resource the host page has opinions about.
 */

import { type Event, initialState, reduce, secondsRemaining } from "./machine";
import { TransportError, type Transport } from "./transport";
import type { AnyStaffSlot, BookingState, FlowError, Service, StaffChoice } from "./types";
import { ANYONE } from "./types";

export interface FlowOptions {
  transport: Transport;
  slug: string;
  now?: () => number;
  /** Stable across retries of one logical confirm — see `web/lib/api.ts`. */
  requestId?: () => string;
}

function classify(error: unknown): FlowError {
  if (error instanceof TransportError) {
    if (error.status === 409) {
      return { kind: "slot_taken", message: error.message };
    }
    if (error.status === 429) {
      return {
        kind: "too_many_holds",
        message: error.message,
        retryAfter: error.body?.retry_after,
      };
    }
    if (error.status >= 400 && error.status < 500) {
      return { kind: "bad_request", message: error.message };
    }
    return { kind: "server", message: "The shop's booking system is not answering." };
  }
  // No status at all: DNS, timeout, aeroplane mode. The client booking page is
  // opened from a WhatsApp link on 3G, so this is an ordinary case, not an edge
  // one, and it must not read like a crash.
  return { kind: "offline", message: "No connection. Check your data and try again." };
}

export function createBookingFlow({ transport, slug, now, requestId }: FlowOptions) {
  const clock = now ?? (() => Date.now());
  const newId = requestId ?? (() => `${clock()}-${Math.random().toString(36).slice(2)}`);

  let state: BookingState = initialState;
  const listeners = new Set<(state: BookingState) => void>();
  /** Reused across retries of one confirm, so a retry cannot double-hold. */
  let confirmRequestId: string | null = null;

  function emit(event: Event) {
    const next = reduce(state, event);
    if (next === state) return state;
    state = next;
    for (const listener of listeners) listener(state);
    return state;
  }

  async function guarded<T>(work: () => Promise<T>): Promise<T | null> {
    emit({ type: "BUSY", busy: true });
    try {
      const result = await work();
      emit({ type: "BUSY", busy: false });
      return result;
    } catch (error) {
      emit({ type: "FAILED", error: classify(error) });
      return null;
    }
  }

  return {
    getState: () => state,

    subscribe(listener: (state: BookingState) => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },

    /** Screen 1's data. Shop and services in parallel — one round trip's worth
     *  of latency, not two, on a connection where that is the whole budget. */
    async load() {
      return guarded(async () => {
        const [shop, services] = await Promise.all([
          transport.getShop(slug),
          transport.getServices(slug),
        ]);
        emit({ type: "SHOP_LOADED", shop, services });
        return shop;
      });
    },

    async chooseService(service: Service) {
      emit({ type: "CHOOSE_SERVICE", service });
      return guarded(async () => {
        const staff = await transport.getStaff(slug, service.id);
        emit({ type: "STAFF_LOADED", staff });
        return staff;
      });
    },

    chooseStaff(choice: StaffChoice) {
      emit({ type: "CHOOSE_STAFF", choice });
    },

    async chooseDate(date: string) {
      emit({ type: "CHOOSE_DATE", date });
      return this.loadAvailability();
    },

    async loadAvailability() {
      const { service, staffChoice, date } = state;
      if (!service || !date) return null;
      return guarded(async () => {
        const availability = await transport.getAvailability(
          slug,
          service.id,
          date,
          // "Anyone" asks for everybody and lets the server pick the earliest
          // per start time. Asking per stylist and merging here would be an
          // assignment algorithm in the client — CLAUDE.md §12 says no.
          staffChoice && staffChoice !== ANYONE ? staffChoice : undefined
        );
        emit({ type: "AVAILABILITY_LOADED", availability });
        return availability;
      });
    },

    chooseSlot(slot: AnyStaffSlot) {
      emit({ type: "CHOOSE_SLOT", slot });
    },

    setPhone(phone: string) {
      emit({ type: "SET_PHONE", phone });
    },

    /**
     * The confirm step. Creates the hold; slice 6 adds the STK push after it.
     *
     * The request id is minted once per confirm attempt and kept, so a client
     * on 3G who taps twice gets one hold rather than a second that collides
     * with their own first.
     */
    async confirm() {
      const { service, slot, phone } = state;
      if (!service || !slot) return null;
      confirmRequestId = confirmRequestId ?? newId();
      const hold = await guarded(() =>
        transport.createHold(slug, {
          service: service.id,
          staff: slot.staff_id,
          starts_at: slot.starts_at,
          phone,
          client_request_id: confirmRequestId!,
        })
      );
      if (hold) emit({ type: "HOLD_CREATED", hold });
      return hold;
    },

    /** Poll while the countdown runs. Slice 6 turns this into the STK screen's
     *  wait; here it is what notices the server released the slot. */
    async refreshHold() {
      if (!state.hold) return null;
      try {
        const hold = await transport.getHold(state.hold.id);
        if (hold.status === "cancelled") {
          emit({ type: "HOLD_RELEASED" });
          confirmRequestId = null;
          return hold;
        }
        emit({ type: "HOLD_UPDATED", hold });
        return hold;
      } catch (error) {
        // A failed poll is not a failed booking. The hold's expiry is the
        // server's, and the countdown keeps running off the timestamp it
        // already has.
        emit({ type: "FAILED", error: classify(error) });
        return null;
      }
    },

    async release() {
      if (!state.hold) return null;
      const id = state.hold.id;
      confirmRequestId = null;
      return guarded(async () => {
        const hold = await transport.releaseHold(id);
        emit({ type: "HOLD_RELEASED" });
        return hold;
      });
    },

    back() {
      emit({ type: "BACK" });
    },

    /** Called by whatever draws the countdown. Returns seconds left. */
    tick(): number {
      return secondsRemaining(state, clock());
    },
  };
}

export type BookingFlow = ReturnType<typeof createBookingFlow>;
