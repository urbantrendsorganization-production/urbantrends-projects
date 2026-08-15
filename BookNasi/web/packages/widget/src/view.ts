/**
 * The eight screens, as data. No DOM, no timers, no network, no framework.
 *
 * This file is the widget's answer to the question `packages/booking-core`
 * exists to make answerable: **is the widget a second renderer, or a second
 * implementation?** Every decision below comes from a selector — `stepFor`
 * chose the screen, `offeredSlots` chose the slots, `canContinue` and
 * `blockedReason` chose whether Continue is live and what it says when it is
 * not, `countdownLabel` chose the countdown's words. There is no
 * `if (payment.state === "succeeded")` here, and there must never be one: that
 * branch already exists, in a tested module, and a copy of it in the widget
 * would be a copy that drifts.
 *
 * What this file *does* own is what a renderer owns — arrangement, and the copy
 * that is specific to being inside somebody else's page.
 *
 * ## The four invariants, and where each one is
 *
 * 1. **52 px targets** — every control carries `bn-target`, `bn-cta`, `bn-slot`
 *    or `bn-day`, and all four carry the floor in `css.ts` in literal pixels.
 *    A control with none of those classes fails `check-widget.mjs`.
 * 2. **Three per row** — `bn-slots`, from `INVARIANTS.slotsPerRow`.
 * 3. **The countdown stays visible** — `waitingPanel` is called unconditionally
 *    on every screen that has a live hold, and it renders `countdownLabel`
 *    rather than a raw number, so a timer at zero with a push still outstanding
 *    reads "Still checking with M-Pesa" instead of claiming an expiry the
 *    server has not declared. There is no flag that suppresses it.
 * 4. **`*334#`** — from `INVARIANTS.ussdFallback`, never typed. A host may
 *    translate the sentence around it; the number is not theirs to remove.
 *
 * ## The word "deposit" appears nowhere in this file
 *
 * It is a copy token (CLAUDE.md §10). The design's neutral-widget mock relabels
 * it "reservation fee", and a shop that calls it a booking fee is entitled to
 * say so. So the word arrives through `ctx.config.copy` and is passed to
 * `refundSentence` as `depositWord`, and `check-widget.mjs` fails the build if a
 * string literal in here contains it — which is why the copy is assembled from
 * child arrays rather than template literals in the places it appears.
 *
 * What the host may **not** do is remove the refund sentence. It is the terms
 * of the money, read before the money moves (CLAUDE.md §5), and it is rendered
 * from `refundSentence` on the confirm screen with no conditional around it.
 */

import { INVARIANTS } from "@booknasi/tokens";
import {
  ANYONE,
  type AnyStaffSlot,
  type BookingState,
  type Hold,
  type Service,
  blockedReason,
  canContinue,
  canResend,
  clock,
  countdownLabel,
  isPaymentStep,
  money,
  offeredSlots,
  refundSentence,
  spellDuration,
  stepNumber,
} from "@booknasi/booking-core";

import type { WidgetConfig } from "./config";
import { type Action, type Child, type VNode, h, on } from "./vdom";

export interface ViewContext {
  config: WidgetConfig;
  /** Seconds left on the hold, from the renderer's clock. */
  seconds: number;
  /** Today in EAT, `YYYY-MM-DD`. Passed in so this file owns no clock. */
  today: string;
}

const TITLES: Record<string, string> = {
  service: "What are you booking?",
  staff: "Who with?",
  slot: "When?",
  confirm: "Confirm and pay",
  held: "Your slot is held",
  pushed: "Check your phone",
  paid: "Booked",
  failed: "That payment didn't go through",
  timedOut: "The hold has run out",
  slotLost: "We received your payment",
};

export function render(state: BookingState, ctx: ViewContext): VNode {
  // `bn-screen`, never `bn-root`. The token scope and the host's inline
  // overrides live on the mount container, which the patcher never touches;
  // a `.bn-root` in here would redeclare the palette and shadow them. See the
  // note in css.ts — this cost a working re-skin.
  return h("div", { class: "bn-screen" }, [
    header(state),
    state.error ? errorPanel(state) : null,
    body(state, ctx),
  ]);
}

function body(state: BookingState, ctx: ViewContext): Child {
  switch (state.step) {
    case "service":
      return serviceList(state, ctx);
    case "staff":
      return staffList(state);
    case "slot":
      return slotPicker(state, ctx);
    case "confirm":
      return confirm(state, ctx);
    case "held":
      return held(state, ctx);
    case "pushed":
      return pushed(state, ctx);
    case "paid":
      return paid(state);
    case "failed":
      return failed(state, ctx);
    case "timedOut":
      return timedOut(state);
    case "slotLost":
      return slotLost(state);
    default:
      return null;
  }
}

function header(state: BookingState): VNode {
  const numbered = state.step !== "held" && !isPaymentStep(state.step);
  return h("header", { class: "bn-stack-tight" }, [
    state.shop
      ? h("p", { class: "bn-shop" }, [state.shop.name + (state.shop.area ? ` · ${state.shop.area}` : "")])
      : null,
    h("div", { class: "bn-row" }, [
      h("h1", { class: "bn-title bn-grow" }, [TITLES[state.step] ?? ""]),
      numbered ? h("span", { class: "bn-mono bn-muted bn-fixed" }, [`${stepNumber(state)} / 4`]) : null,
    ]),
    // No Back on a payment screen. The money either moved or it did not, and a
    // back arrow that appears to undo it is the most expensive lie here.
    state.step !== "service" && state.step !== "held" && !isPaymentStep(state.step)
      ? on(
          h("button", { type: "button", class: "bn-target bn-secondary", style: "width:auto" }, [
            "← Back",
          ]),
          "click",
          { type: "back" },
        )
      : null,
  ]);
}

function errorPanel(state: BookingState): VNode {
  const lost = state.error?.kind === "slot_taken";
  return h(
    "div",
    {
      role: "alert",
      class: `bn-panel bn-error ${lost ? "bn-panel-fail" : "bn-panel-info"}`,
    },
    [state.error?.message ?? ""],
  );
}

// --------------------------------------------------------------- screen 1

function serviceList(state: BookingState, ctx: ViewContext): VNode {
  const { copy } = ctx.config;
  return h("section", { class: "bn-stack-tight" }, [
    // The reassurance strip, and the terms, before anything is asked. A client
    // should never meet the money for the first time at the end.
    h("p", { class: "bn-panel bn-panel-pay bn-note" }, [
      "A ",
      copy.deposit,
      " by M-Pesa holds your slot. ",
      state.shop
        ? refundSentence(
            state.shop.refund_window_hours,
            state.shop.deposit_credit_days,
            copy.deposit,
          )
        : "",
    ]),
    ...state.services.map((service) => serviceCard(service, state.service?.id === service.id, ctx)),
    !state.services.length && !state.busy
      ? h("p", { class: "bn-empty" }, ["This shop has nothing bookable online yet."])
      : null,
  ]);
}

function serviceCard(service: Service, selected: boolean, ctx: ViewContext): VNode {
  return on(
    h(
      "button",
      {
        type: "button",
        class: "bn-target bn-card-target",
        "aria-pressed": selected,
        key: `service-${service.id}`,
      },
      [
        h("span", { class: "bn-row" }, [
          // The name wraps and is never truncated on the client side — the
          // design's rule. `bn-grow` is what stops a long one pushing the price
          // out of its column.
          h("span", { class: "bn-grow" }, [service.name]),
          h("span", { class: "bn-mono bn-strong bn-fixed" }, [money(service.price)]),
        ]),
        h("span", { class: "bn-row", style: "margin-top:8px;flex-wrap:wrap" }, [
          h("span", { class: "bn-mono bn-muted" }, [spellDuration(service.duration_minutes)]),
          // The deposit is priced on every card, before anything else is asked.
          h("span", { class: "bn-pill" }, [money(service.deposit_amount), " ", ctx.config.copy.deposit]),
        ]),
      ],
    ),
    "click",
    { type: "chooseService", id: service.id },
  );
}

// --------------------------------------------------------------- screen 2

function staffList(state: BookingState): VNode {
  const soonest = state.availability?.any_staff[0];
  return h("section", { class: "bn-stack-tight" }, [
    // First and pre-selected, and it is earliest-available-slot rather than an
    // assignment algorithm — CLAUDE.md §12.
    choice(
      state.staffChoice === ANYONE,
      "Anyone available",
      soonest ? `Soonest: ${clock(soonest.starts_at)}` : "Whoever is free first",
      { type: "chooseStaff", id: ANYONE },
      "staff-anyone",
    ),
    ...state.staffOptions.map((person) =>
      choice(
        state.staffChoice === person.id,
        person.display_name,
        // Their own duration for this service — CLAUDE.md §3. Two stylists
        // genuinely take different times over the same job, and the schedule
        // has to be able to say so.
        spellDuration(person.duration_minutes),
        { type: "chooseStaff", id: person.id },
        `staff-${person.id}`,
      ),
    ),
    h("p", { class: "bn-note" }, ["Times differ by stylist."]),
  ]);
}

function choice(
  selected: boolean,
  title: string,
  detail: string,
  action: Action,
  key: string,
): VNode {
  return on(
    h("button", { type: "button", class: "bn-target", "aria-pressed": selected, key }, [
      h("span", { class: "bn-grow" }, [title]),
      h("span", { class: "bn-muted bn-fixed bn-note" }, [detail]),
    ]),
    "click",
    action,
  );
}

// --------------------------------------------------------------- screen 3

function slotPicker(state: BookingState, ctx: ViewContext): VNode {
  const slots = offeredSlots(state);
  return h("section", {}, [
    dayStrip(state.date, ctx.today),
    ...(slots.length
      ? slotGroups(slots, state.slot)
      : [
          state.busy
            ? null
            : // The design's rule: never a generic apology, always the next real
              // option — and where there is none, say so plainly.
              h("p", { class: "bn-empty" }, [
                "Nothing free that day. Try another date, or pick “Anyone available”.",
              ]),
        ]),
  ]);
}

function dayStrip(selected: string | null, today: string): VNode {
  const days = Array.from({ length: 7 }, (_, offset) => {
    const day = new Date(`${today}T00:00:00Z`);
    day.setUTCDate(day.getUTCDate() + offset);
    return day.toISOString().slice(0, 10);
  });
  return h(
    "div",
    { class: "bn-days" },
    days.map((day) =>
      on(
        h("button", { type: "button", class: "bn-day", "aria-pressed": selected === day, key: day }, [
          new Date(`${day}T00:00:00Z`).toLocaleDateString("en-GB", {
            timeZone: "Africa/Nairobi",
            weekday: "short",
            day: "numeric",
          }),
        ]),
        "click",
        { type: "chooseDate", date: day },
      ),
    ),
  );
}

function slotGroups(slots: AnyStaffSlot[], chosen: AnyStaffSlot | null): VNode[] {
  const groups: [string, AnyStaffSlot[]][] = [
    ["Morning", slots.filter((slot) => Number(slot.local_time.slice(0, 2)) < 12)],
    ["Afternoon", slots.filter((slot) => Number(slot.local_time.slice(0, 2)) >= 12)],
  ];
  return groups
    .filter(([, group]) => group.length > 0)
    .map(([label, group]) =>
      h("div", { style: "margin-bottom:20px", key: `group-${label}` }, [
        h("h2", { class: "bn-label", style: "margin-bottom:10px" }, [label]),
        // CLAUDE.md §10, invariant 2. The grid's columns come from
        // INVARIANTS.slotsPerRow in css.ts, not from a number written here.
        h(
          "div",
          { class: "bn-slots" },
          group.map((slot) =>
            on(
              h(
                "button",
                {
                  type: "button",
                  class: "bn-slot",
                  "aria-pressed": chosen?.starts_at === slot.starts_at,
                  key: `${slot.staff_id}-${slot.starts_at}`,
                },
                [slot.local_time],
              ),
              "click",
              { type: "chooseSlot", startsAt: slot.starts_at },
            ),
          ),
        ),
      ]),
    );
}

// --------------------------------------------------------------- screen 4

function confirm(state: BookingState, ctx: ViewContext): VNode {
  const service = state.service;
  const slot = state.slot;
  const { copy } = ctx.config;
  if (!service || !slot) return h("section", {}, []);
  const blocked = blockedReason(state);
  return h("section", { class: "bn-stack" }, [
    h("div", { class: "bn-card" }, [
      h("div", { class: "bn-mono bn-big" }, [`${clock(slot.starts_at)} → ${clock(slot.ends_at)}`]),
      h("p", { class: "bn-muted", style: "margin-top:4px" }, [`${service.name} · ${slot.staff_name}`]),
    ]),

    h("div", { class: "bn-card" }, [
      line("Total", money(service.price)),
      line([copy.depositTitleCase, " now"], money(service.deposit_amount), true),
      line("Balance at the shop", money(service.balance_due)),
      // The terms, inside the same card as the money and above the button that
      // moves it. CLAUDE.md §10: a host may translate or relabel this sentence
      // and may not remove it — there is no condition around this call.
      h("p", { class: "bn-note", style: "margin-top:12px" }, [
        refundSentence(
          state.shop?.refund_window_hours ?? 24,
          state.shop?.deposit_credit_days ?? 60,
          copy.deposit,
        ),
      ]),
    ]),

    h("div", { class: "bn-card" }, [
      h("label", { class: "bn-stack-tight" }, [
        h("span", { class: "bn-label" }, ["M-Pesa number"]),
        h("span", { class: "bn-phone" }, [
          h("span", { class: "bn-phone-prefix" }, ["+254"]),
          on(
            h("input", {
              class: "bn-phone-input",
              inputmode: "tel",
              autocomplete: "tel",
              placeholder: "712 345 678",
              value: state.phone,
              // Keyed so the patcher reuses the node. Replacing a focused input
              // mid-booking drops the keyboard on a phone, which on this screen
              // costs the deposit.
              key: "phone",
            }),
            "input",
            { type: "setPhone" },
          ),
        ]),
      ]),
    ]),

    on(
      h(
        "button",
        { type: "button", class: "bn-cta", disabled: !canContinue(state) },
        // A disabled button's label says why — the design's rule.
        blocked ? [blocked] : ["Hold my slot · ", money(service.deposit_amount), " ", copy.deposit],
      ),
      "click",
      { type: "confirm" },
    ),
    h("p", { class: "bn-note" }, ["You'll get an M-Pesa prompt on this phone."]),
  ]);
}

function line(label: Child[] | string, value: string, strong = false): VNode {
  return h("div", { class: "bn-line" }, [
    h("span", { class: strong ? "" : "bn-muted" }, Array.isArray(label) ? label : [label]),
    h("span", { class: `bn-mono bn-fixed ${strong ? "bn-strong" : ""}` }, [value]),
  ]);
}

// ------------------------------------------------ the hold, with no payment

function held(state: BookingState, ctx: ViewContext): Child {
  const hold = state.hold;
  if (!hold) return null;
  return h("section", { class: "bn-stack" }, [
    h("div", { class: "bn-card" }, [
      h("div", { class: "bn-mono bn-big" }, [`${clock(hold.starts_at)} · ${hold.staff_name}`]),
      h("p", { class: "bn-muted", style: "margin-top:4px" }, [hold.service_name]),
    ]),
    waitingPanel(state, ctx),
    on(h("button", { type: "button", class: "bn-cta bn-secondary" }, ["Give up this slot"]), "click", {
      type: "release",
    }),
  ]);
}

// ----------------------------------------------------------- screens 5 to 8

function pushed(state: BookingState, ctx: ViewContext): Child {
  const hold = state.hold;
  if (!hold) return null;
  const amount = hold.payment?.amount_kes ?? hold.deposit_kes;
  return h("section", { class: "bn-stack" }, [
    waitingPanel(state, ctx),
    h("div", { class: "bn-card" }, [
      h("p", {}, ["Enter your M-Pesa PIN to pay ", h("strong", { class: "bn-mono" }, [money(amount)]), "."]),
      // CLAUDE.md §10, invariant 4. From the constant, never typed, and never
      // behind a tap: when the push does not arrive — and it often does not —
      // this line is the difference between a completed payment and an
      // abandoned booking.
      h("p", { class: "bn-note", style: "margin-top:10px" }, [
        "No prompt? Dial ",
        h("strong", { class: "bn-mono" }, [INVARIANTS.ussdFallback]),
        " and choose M-Pesa, then Pay Bill.",
      ]),
    ]),
    resendButton(state, ctx, "Resend the prompt"),
    shopFallback(hold),
  ]);
}

/** Screen 6. The receipt is first, because it is the proof at the door. */
function paid(state: BookingState): Child {
  const hold = state.hold;
  if (!hold) return null;
  const payment = hold.payment;
  return h("section", { class: "bn-stack" }, [
    h("div", { class: "bn-panel bn-panel-pay" }, [
      h("p", { class: "bn-label" }, ["M-Pesa"]),
      h("p", { class: "bn-mono bn-big", style: "margin-top:4px" }, [
        payment?.mpesa_receipt || payment?.support_code || "",
      ]),
      h("p", { style: "margin-top:10px" }, [
        money(payment?.amount_kes ?? hold.deposit_kes),
        " received.",
      ]),
    ]),
    h("div", { class: "bn-card" }, [
      h("div", { class: "bn-mono bn-big" }, [`${clock(hold.starts_at)} · ${hold.staff_name}`]),
      h("p", { class: "bn-muted", style: "margin-top:4px" }, [hold.service_name]),
      h("div", { style: "margin-top:12px" }, [line("Balance at the shop", money(hold.balance_kes))]),
    ]),
    h("p", { class: "bn-note" }, [
      "We've sent you a confirmation by SMS, and we'll remind you before your appointment.",
    ]),
  ]);
}

/**
 * Screen 7. The payment failed and the hold is still alive.
 *
 * The countdown stays, because the retry has to happen inside it. The design's
 * "book a deposit-free service instead" offer is not here, for the same reason
 * it is not in the standalone app: it sends a client hunting through a service
 * list at the worst possible moment, and the thing they actually wanted is
 * still theirs for another minute or two.
 */
function failed(state: BookingState, ctx: ViewContext): Child {
  const hold = state.hold;
  if (!hold) return null;
  return h("section", { class: "bn-stack" }, [
    // The server's copy, never Safaricom's raw ResultDesc. "Merchant does not
    // exist" is our problem, not the client's.
    h("div", { class: "bn-panel bn-panel-fail" }, [hold.payment?.message ?? ""]),
    waitingPanel(state, ctx),
    resendButton(state, ctx, "Try again"),
    h("p", { class: "bn-note" }, [
      "Or dial ",
      h("strong", { class: "bn-mono" }, [INVARIANTS.ussdFallback]),
      " and pay by Pay Bill.",
    ]),
    shopFallback(hold),
  ]);
}

function timedOut(state: BookingState): Child {
  const hold = state.hold;
  if (!hold) return null;
  return h("section", { class: "bn-stack" }, [
    h("div", { class: "bn-card" }, [
      h("p", {}, [`${hold.local_time} is back in the list and nothing was taken from your M-Pesa.`]),
    ]),
    on(h("button", { type: "button", class: "bn-cta" }, ["Pick another time"]), "click", {
      type: "release",
    }),
    shopFallback(hold),
  ]);
}

/**
 * Screen 8 — `slotLost`. The money arrived and the slot did not survive.
 *
 * The lead action is the client's own remedy: pick another time and the
 * succeeded payment is re-pointed at it, with no second push. The support code
 * and the shop's number stay below it, because a re-point can lose its own race
 * and the client whose second choice also went still needs a human.
 *
 * What this screen must never say is that a refund is automatic. Nothing
 * automatic exists, the money is with the shop rather than with us, and
 * `check-widget.mjs` asserts the promise is absent — the same assertion the
 * standalone app carries, for the same reason (CLAUDE.md §12).
 */
function slotLost(state: BookingState): Child {
  const hold = state.hold;
  if (!hold) return null;
  const payment = hold.payment;
  const amount = money(payment?.amount_kes ?? hold.deposit_kes);
  return h("section", { class: "bn-stack" }, [
    h("div", { class: "bn-panel bn-panel-fail" }, [
      h("p", {}, [
        "We received your ",
        amount,
        ", but ",
        hold.local_time,
        " was taken while the payment was going through.",
      ]),
      h("p", { style: "margin-top:12px" }, [
        "Nothing is lost. Pick another time below and your ",
        amount,
        " comes with it.",
      ]),
    ]),
    h("div", { class: "bn-card" }, [
      h("p", { class: "bn-label" }, ["Quote this code"]),
      h("p", { class: "bn-mono bn-big", style: "margin-top:4px" }, [payment?.support_code ?? ""]),
      payment?.mpesa_receipt
        ? h("p", { class: "bn-note", style: "margin-top:8px" }, [`M-Pesa ${payment.mpesa_receipt}`])
        : null,
    ]),
    on(h("button", { type: "button", class: "bn-cta" }, ["Pick another time"]), "click", {
      type: "pickAnotherTime",
    }),
    shopFallback(hold),
  ]);
}

/**
 * CLAUDE.md §10, invariant 3.
 *
 * Called unconditionally by every screen that has a live hold. There is no
 * `showCountdown` parameter and no class that hides it, because the failure
 * this guards against is not deletion — it is a tidy-up that puts the timer
 * behind a disclosure, or renders the raw seconds so that zero reads as
 * "expired" while the server is still holding the slot through its grace
 * window. `countdownLabel` is what keeps the second one honest.
 */
function waitingPanel(state: BookingState, ctx: ViewContext): VNode {
  const hold = state.hold;
  const total = (state.shop?.hold_ttl_minutes ?? 3) * 60;
  const label = countdownLabel(state, ctx.seconds);
  const stillChecking = ctx.seconds <= 0 && (hold?.payment?.push_outstanding ?? false);
  const width = Math.max(0, Math.min(100, (ctx.seconds / total) * 100));
  return h("div", { class: "bn-panel bn-panel-hold" }, [
    h("div", { class: "bn-row", style: "justify-content:space-between" }, [
      h("span", {}, [stillChecking ? "Your slot" : "Slot held for"]),
      h("span", { class: `bn-mono bn-strong ${stillChecking ? "" : "bn-big"}` }, [label]),
    ]),
    // The one element below the 52px floor, and the reason it is allowed:
    // aria-hidden, so it is not in the accessibility tree, not focusable and
    // not reachable by any user by any means. A 52px bar here would obstruct
    // the screen the floor exists to keep usable.
    h("div", { class: "bn-track", "aria-hidden": "true" }, [
      h("div", { class: "bn-track-fill", style: `width:${width}%` }, []),
    ]),
    h("p", { class: "bn-note", style: "margin-top:12px" }, [
      stillChecking
        ? "M-Pesa is slow sometimes. We're still holding your time while we check."
        : `Nobody else can take ${hold?.local_time ?? "your time"} until the timer runs out.`,
    ]),
  ]);
}

function resendButton(state: BookingState, ctx: ViewContext, label: string): VNode {
  const allowed = canResend(state, ctx.seconds);
  return on(
    h("button", { type: "button", class: "bn-cta bn-secondary", disabled: !allowed }, [
      state.busy ? "Sending…" : label,
    ]),
    "click",
    { type: "resend" },
  );
}

/**
 * The shop's number, and the sentence that has to sit beside it.
 *
 * This replaced "Pay at the shop instead". That control implied the slot was
 * being held while the client travelled, and it is not — the hold is a few
 * minutes long and the deposit is what keeps it. A WhatsApp link would have
 * made the same implication more politely.
 */
function shopFallback(hold: Hold): Child {
  if (!hold.shop_phone) return null;
  return h("p", { class: "bn-note" }, [
    "Stuck? Call the shop on ",
    h("a", { class: "bn-link", href: `tel:${hold.shop_phone}` }, [hold.shop_phone]),
    ". This time is not being held for you once the timer runs out.",
  ]);
}
