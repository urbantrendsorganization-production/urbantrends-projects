/**
 * Reading the staff day: bands, clocks, labels.
 *
 * Banding happens here rather than on the server — see `scheduling/dayview.py`.
 * The three bands the design draws (Now / Next / earlier work in grey) are all
 * functions of the current second, and a band computed at request time would be
 * wrong before it painted. The server sends statuses and instants; this file
 * and one `setInterval` do the rest.
 *
 * Money and times render mono with tabular figures, per the type spec. Times
 * are 12-hour with a space ("10:00 am"), durations spelled ("3 hr 30 min").
 */

export type Appointment = {
  id: string;
  status: string;
  status_label: string;
  source: string;
  is_waiting: boolean;
  starts_at: string;
  ends_at: string;
  booked_ends_at: string;
  started_at: string | null;
  finished_at: string | null;
  local_time: string;
  staff_id: string;
  staff_name: string;
  service_name: string;
  client_name: string;
  client_phone: string;
  price_kes: number;
  deposit_kes: number;
  duration_minutes: number;
  undo_to: string | null;
  /** Client-side only. Set on a row that has not been acknowledged yet. */
  pending?: "sending" | "failed";
  pendingDetail?: string;
  /** Client-side only. Lets "Try again" rebuild the request without retaping. */
  serviceId?: string;
};

export type Band = "now" | "next" | "earlier";

const DONE = new Set(["completed", "no_show", "cancelled"]);

export function bandFor(appointment: Appointment, now: Date): Band {
  if (appointment.status === "in_progress") return "now";
  if (DONE.has(appointment.status)) return "earlier";
  const starts = new Date(appointment.starts_at).getTime();
  const ends = new Date(appointment.booked_ends_at).getTime();
  // A confirmed booking whose time has arrived is the one on the chair now,
  // whether or not anybody remembered to hit Start. Putting it under "Next"
  // would hide the row a staff member is standing in front of.
  if (starts <= now.getTime() && now.getTime() < ends) return "now";
  if (ends <= now.getTime()) return "earlier";
  return "next";
}

export function groupByBand(appointments: Appointment[], now: Date) {
  const bands: Record<Band, Appointment[]> = { now: [], next: [], earlier: [] };
  for (const appointment of appointments) bands[bandFor(appointment, now)].push(appointment);
  return bands;
}

const EAT = "Africa/Nairobi";

export function clock(iso: string): string {
  return new Date(iso)
    .toLocaleTimeString("en-GB", {
      timeZone: EAT,
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    })
    .replace(/\s?([ap])\.?m\.?/i, " $1m")
    .toLowerCase();
}

export function spellDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (!hours) return `${rest} min`;
  return rest ? `${hours} hr ${rest} min` : `${hours} hr`;
}

export function elapsedSince(iso: string, now: Date): string {
  const minutes = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 60000));
  return spellDuration(minutes);
}

export function money(kes: number): string {
  return `KES ${kes.toLocaleString("en-KE")}`;
}

/** The design's rule: never a generic apology, always the next real option. */
export function emptyDayLine(nextFree: string | null): string {
  if (!nextFree) return "Nothing booked today. Record a walk-in with the + button.";
  return `Nothing booked today. The next opening is ${clock(nextFree)}.`;
}
