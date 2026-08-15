/**
 * The browser half. The only file in this package that touches a global.
 *
 * Everything that could be moved out of here has been — the screens are in
 * `view.ts`, the reconciler in `patch.ts`, the host's options in `config.ts`,
 * and every decision about the booking itself is in `booking-core`. What is
 * left is the wiring that genuinely needs a browser: a shadow root, two event
 * listeners, one interval, and the switch that turns an `Action` into a call on
 * the flow.
 *
 * `check-widget.mjs` enforces that split. A `document` in `view.ts` fails the
 * build, the same way a React import in `booking-core` does.
 *
 * ## The shadow root
 *
 * Open, not closed. A closed root would stop the host inspecting the widget,
 * which sounds like isolation and is really just an obstacle to the person
 * debugging why the booking widget is blank on their site. It protects nothing:
 * the host runs script on the page and can reach anything they are determined
 * to reach. What the boundary is actually for is CSS — see `css.ts` — and that
 * works identically either way.
 *
 * ## One interval, and what it is for
 *
 * The countdown and the payment poll share a beat, exactly as the standalone
 * app's does. The client is watching a screen that has to rewrite itself when
 * money they moved in a different app reaches a server they cannot see, so it
 * asks: every three seconds while a prompt is live, and once more when the
 * timer reaches zero, because the server's grace window means zero is not the
 * end of the story.
 *
 * It is cleared on `destroy()` and whenever the step stops being one with a
 * live hold. A widget that polls forever inside somebody else's page is a
 * widget that gets removed from it.
 */

import {
  type BookingState,
  createBookingFlow,
  httpTransport,
  offeredSlots,
} from "@booknasi/booking-core";

import type { WidgetConfig } from "./config";
import { stylesheet } from "./css";
import { availabilityKey, pendingRequest } from "./effects";
import { type ElLike, patchChildren } from "./patch";
import type { Action } from "./vdom";
import { render } from "./view";

export interface Mounted {
  destroy(): void;
}

/** The steps with a live hold: the countdown runs and the payment is polled. */
const WATCHED = new Set(["held", "pushed", "failed"]);

export function mount(container: Element, config: WidgetConfig): Mounted {
  const shadow = container.shadowRoot ?? container.attachShadow({ mode: "open" });
  shadow.replaceChildren();

  const style = document.createElement("style");
  style.textContent = stylesheet();
  shadow.appendChild(style);

  // The token scope *and* the element the host's overrides are set on. Those
  // two have to be the same element: an inline `--bn-accent` on a parent is
  // shadowed the moment a descendant carries `.bn-root`, because the
  // stylesheet redeclares every token there. See the note in `css.ts`.
  //
  // It is also the one node the patcher never rebuilds — `patchChildren` works
  // on its children — so the inline properties survive every draw.
  const root = document.createElement("div");
  root.className = "bn-root";
  for (const [property, value] of Object.entries(config.theme)) {
    root.style.setProperty(property, value);
  }
  shadow.appendChild(root);

  const flow = createBookingFlow({
    transport: httpTransport({
      baseUrl: config.apiBase,
      fetchImpl: (url, init) => fetch(url, init),
      // No cookie, and therefore no CSRF token to send with one. See the note
      // on `credentials` in booking-core's transport.
      credentials: "omit",
    }),
    slug: config.slug,
    requestId: () =>
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(36).slice(2)}`,
  });

  const actions = new WeakMap<object, Partial<Record<string, Action>>>();
  let seconds = 0;
  let beat: ReturnType<typeof setInterval> | null = null;
  let alive = true;
  /** The last availability request started. See `effects.ts` — this is what
   *  stops a failed fetch becoming a request loop inside a host's page. */
  let requested: string | null = null;

  function draw() {
    const state = flow.getState();
    const today = todayInEat();
    patchChildren(
      {
        doc: document,
        bind: (el, on) => actions.set(el as object, on),
        isFocused: (el) => shadow.activeElement === (el as unknown as Element),
      },
      root as unknown as ElLike,
      [render(state, { config, seconds, today })],
    );
    // Drawn first, then the beat and the outstanding request are reconsidered:
    // both exist to keep this screen current, so they follow it rather than
    // lead it, and a client always sees the state that produced them.
    retime(state);
    run(pendingRequest(state, today, requested), state);
  }

  /** The slot picker's one asynchronous need. `effects.ts` decides; this does. */
  function run(effect: ReturnType<typeof pendingRequest>, state: BookingState) {
    if (!effect) return;
    if (effect.type === "chooseDate") {
      // Claimed before the call, not after. `flow.chooseDate` loads
      // availability itself and notifies subscribers first, so an unclaimed key
      // means this function runs again from inside that notification and sends
      // the same request twice.
      requested = availabilityKey({ ...state, date: effect.date });
      void flow.chooseDate(effect.date);
      return;
    }
    requested = availabilityKey(state);
    void flow.loadAvailability();
  }

  function retime(state: BookingState) {
    const wanted = WATCHED.has(state.step);
    if (!wanted) {
      if (beat !== null) clearInterval(beat);
      beat = null;
      return;
    }
    if (beat !== null) return;
    seconds = flow.tick();
    let ticks = 0;
    beat = setInterval(() => {
      if (!alive) return;
      seconds = flow.tick();
      ticks += 1;
      if (seconds <= 0 || ticks % 3 === 0) void flow.refreshHold();
      draw();
    }, 1000);
  }

  function dispatch(action: Action, target: EventTarget | null) {
    const state = flow.getState();
    switch (action.type) {
      case "back":
        return flow.back();
      case "chooseService": {
        const service = state.services.find((row) => row.id === action.id);
        if (service) void flow.chooseService(service);
        return;
      }
      case "chooseStaff":
        return flow.chooseStaff(action.id);
      case "chooseDate":
        return run({ type: "chooseDate", date: action.date }, state);
      case "chooseSlot": {
        // Resolved through the same selector the grid was drawn from, so the
        // two cannot disagree about which slot a chip is.
        const slot = offeredSlots(state).find((row) => row.starts_at === action.startsAt);
        if (slot) flow.chooseSlot(slot);
        return;
      }
      case "setPhone":
        return flow.setPhone((target as HTMLInputElement | null)?.value ?? "");
      case "confirm":
        return void flow.confirm();
      case "release":
        return void flow.release();
      case "resend":
        return void flow.resend();
      case "pickAnotherTime":
        return flow.pickAnotherTime();
    }
  }

  /**
   * One listener per event type, on the root, resolved through
   * `composedPath()`.
   *
   * Delegation rather than a listener per control, because the tree is redrawn
   * once a second for three minutes on the payment screens and attaching and
   * detaching a few dozen listeners a second is work with nothing to show for
   * it. `composedPath()` is the shadow-DOM-aware walk — `event.target` inside a
   * shadow root is retargeted to the host element, so the ordinary `closest()`
   * approach would find nothing.
   */
  function listen(type: "click" | "input") {
    const handler = (event: Event) => {
      for (const node of event.composedPath()) {
        const action = actions.get(node as object)?.[type];
        if (action) {
          if (type === "click") event.preventDefault();
          dispatch(action, node as EventTarget);
          return;
        }
        if (node === root) return;
      }
    };
    root.addEventListener(type, handler);
    return () => root.removeEventListener(type, handler);
  }

  const unlisten = [listen("click"), listen("input")];
  const unsubscribe = flow.subscribe(() => draw());

  draw();
  void flow.load();

  return {
    destroy() {
      alive = false;
      if (beat !== null) clearInterval(beat);
      beat = null;
      for (const off of unlisten) off();
      unsubscribe();
      shadow.replaceChildren();
    },
  };
}

/**
 * Today, in EAT, as `YYYY-MM-DD`.
 *
 * Not `new Date().toISOString().slice(0, 10)`. A client booking at 1 a.m. in
 * Nairobi is on yesterday's UTC date, and the day strip would open on a day
 * that has already gone — with every slot in it unavailable, which reads as a
 * fully booked shop. CLAUDE.md §4: store UTC, render EAT, and there is exactly
 * one timezone to render.
 */
export function todayInEat(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Africa/Nairobi",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}
