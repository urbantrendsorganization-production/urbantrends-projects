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

export interface Hold {
  id: string;
  status: string;
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

export type Step = "service" | "staff" | "slot" | "confirm" | "held";

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
