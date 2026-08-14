/**
 * The API's shapes, as the client sees them.
 *
 * Named after the JSON rather than prettified into camelCase. A rename layer
 * would be one more place for the widget and the standalone app to disagree,
 * and the field names are the public API's contract — CLAUDE.md §1 says a third
 * party will integrate it, and they will be reading these names, not ours.
 */

export interface Shop {
  slug: string;
  name: string;
  address: string;
  area: string;
  directions_url: string;
  phone: string;
  logo_url: string;
  accent_color: string;
  /** Drives the countdown. CLAUDE.md §10: it is never hidden. */
  hold_ttl_minutes: number;
  /** The refund rule is stated before payment, never after. */
  refund_window_hours: number;
  /** How long a late cancellation's deposit stays usable as shop credit. */
  deposit_credit_days: number;
  opening_hours: { weekday: number; opens_at: string; closes_at: string }[];
}

export interface Service {
  id: string;
  name: string;
  description: string;
  duration_minutes: number;
  price: number;
  deposit_mode: string;
  /** The exact figure slice 6 will push to M-Pesa. Never recomputed here. */
  deposit_amount: number;
  balance_due: number;
}

export interface StaffOption {
  id: string;
  display_name: string;
  /** This stylist's own duration for the chosen service — CLAUDE.md §3. */
  duration_minutes: number;
}

export interface Slot {
  starts_at: string;
  ends_at: string;
  local_time: string;
  duration_minutes: number;
}

/** A slot from the "anyone available" list, carrying whoever owns it. */
export interface AnyStaffSlot extends Slot {
  staff_id: string;
  staff_name: string;
}

export interface Availability {
  date: string;
  service_id: string;
  any_staff: AnyStaffSlot[];
  by_staff: { staff_id: string; display_name: string; slots: Slot[] }[];
}

/**
 * The payment, as the waiting screen needs it.
 *
 * `push_outstanding` is the field the countdown cannot do without. Without it,
 * a client whose timer reaches 0:00 while Safaricom is still thinking is told
 * their slot expired — which is the unexplained failure CLAUDE.md §10 invariant
 * 3 exists to prevent, arriving through the one control the invariant protects.
 * With it the screen says "still checking with M-Pesa" and stays honest.
 *
 * `message` is client-safe copy chosen by the server, never Safaricom's raw
 * `ResultDesc`. "Merchant does not exist" is our problem, not the client's.
 */
export interface PaymentView {
  /** `initiated | pushed | push_failed | succeeded | failed |
   *  cancelled_by_user | unknown | superseded | orphaned`. */
  state: string;
  amount_kes: number;
  /** What the client reads down the phone. Present as soon as a push exists. */
  support_code: string;
  mpesa_receipt: string;
  /** A prompt may still be answered. See above. */
  push_outstanding: boolean;
  message: string;
  /** The money arrived and the slot did not survive. Screen 8. */
  slot_lost: boolean;
}

/** The refund terms, as two numbers the copy is rendered from. See §12. */
export interface RefundTerms {
  refund_window_hours: number;
  deposit_credit_days: number;
}

export interface Hold extends RefundTerms {
  id: string;
  status: string;
  /** For the booking page the confirmation SMS links to, which has no shop. */
  shop_name: string;
  starts_at: string;
  ends_at: string;
  local_time: string;
  hold_expires_at: string;
  seconds_remaining: number;
  staff_name: string;
  service_name: string;
  price_kes: number;
  deposit_kes: number;
  balance_kes: number;
  /** Null until a push has been attempted. */
  payment: PaymentView | null;
  /** The number on screen 5's fallback line and screen 8's footer. */
  shop_phone: string;
}

export interface HoldRequest {
  service: string;
  staff: string;
  starts_at: string;
  phone: string;
  client_request_id?: string;
}

/** What went wrong, in the shape the flow can act on. */
export interface FlowError {
  /** `slot_taken`, `too_many_holds`, `bad_request`, `offline`. */
  kind: string;
  message: string;
  /** Seconds, when the server said when to come back. */
  retryAfter?: number;
}

/** `ANYONE` is the design's pre-selected first option on screen 2. */
export const ANYONE = "anyone" as const;
export type StaffChoice = string | typeof ANYONE;

/**
 * `held` is slice 5's hold with no payment against it. The five that follow are
 * slice 6, and they are derived from the payment's state rather than set by the
 * renderer — see `stepFor` in `machine.ts`. A screen the client can be *put*
 * into is a screen that can disagree with the server about whether money moved.
 *
 * - `pushed`    — screen 5. The prompt is on the phone; the countdown runs.
 * - `paid`      — screen 6. Receipt first; it is the proof at the door.
 * - `failed`    — screen 7. Named reason, retry inside the remaining hold.
 * - `timedOut`  — the push was never answered and the hold has gone.
 * - `slotLost`  — screen 8. The money arrived, the slot did not survive.
 */
export type Step =
  | "service"
  | "staff"
  | "slot"
  | "confirm"
  | "held"
  | "pushed"
  | "paid"
  | "failed"
  | "timedOut"
  | "slotLost";

export interface BookingState {
  step: Step;
  shop: Shop | null;
  services: Service[];
  service: Service | null;
  staffOptions: StaffOption[];
  staffChoice: StaffChoice | null;
  /** EAT calendar date, `YYYY-MM-DD`. */
  date: string | null;
  availability: Availability | null;
  slot: AnyStaffSlot | null;
  phone: string;
  hold: Hold | null;
  /** Set while a request is in flight, so the CTA can say what it is doing. */
  busy: boolean;
  error: FlowError | null;
}
