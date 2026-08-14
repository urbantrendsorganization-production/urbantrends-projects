/**
 * Formatting that must match what the server said, exactly.
 *
 * The design's rule: money is always `KES 1,000`, never `1.5k`, in mono with
 * tabular figures. Times are 12-hour with a space; durations are spelled.
 *
 * Nothing here computes a deposit. `deposit_amount` arrives from the API as the
 * figure `shops/money.py` produced and slice 6 will push to M-Pesa — one
 * number, computed once, in one place. A client-side percentage would round
 * differently on some price sooner or later, and the number the client agreed
 * to would stop being the number they were charged.
 */

export function money(kes: number): string {
  return `KES ${kes.toLocaleString("en-KE")}`;
}

export function spellDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (!hours) return `${rest} min`;
  return rest ? `${hours} hr ${rest} min` : `${hours} hr`;
}

/** `10:00 am`. The API also sends a 24-hour `local_time`; this is the display
 *  form, kept here so the widget prints it identically. */
export function clock(iso: string, timeZone = "Africa/Nairobi"): string {
  return new Date(iso)
    .toLocaleTimeString("en-GB", { timeZone, hour: "numeric", minute: "2-digit", hour12: true })
    .replace(/\s?([ap])\.?m\.?/i, " $1m")
    .toLowerCase();
}

/** `2:59` on the hold countdown. Never rounded up: a timer that lies is worse
 *  than no timer, and this one is the reason it is safe to leave the page. */
export function countdown(seconds: number): string {
  const safe = Math.max(0, seconds);
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}

/**
 * The sentence the client reads before paying. CLAUDE.md §10: it may be
 * translated or relabelled, never removed. `depositWord` exists because
 * "deposit" is a host-overridable copy token — a luxury salon relabels it
 * "reservation fee" — and the rule has to survive that.
 *
 * All four outcomes of the policy settled on 14 August 2026 (§12), in one
 * sentence, because §5 requires the terms to be read *before* the money moves
 * and a client will read one sentence. The old copy said "after that it is
 * not", which was both wrong under the new policy and the harshest possible
 * reading of it: a late cancellation keeps its value as credit, and the one
 * case that genuinely forfeits is the one the client controls.
 *
 * The shop-cancels clause is last and unconditional on purpose. It is the term
 * a client is most likely to worry about and the one they can do nothing about,
 * so it is the note the sentence ends on.
 */
export function refundSentence(
  refundWindowHours: number,
  creditDays = 60,
  depositWord = "deposit",
): string {
  return (
    `Cancel more than ${refundWindowHours} hours before and your ${depositWord} ` +
    `is refunded; cancel later and it becomes credit at this shop for ` +
    `${creditDays} days, on any service; miss the appointment and it is kept; ` +
    `and if the shop cancels you are refunded either way.`
  );
}
