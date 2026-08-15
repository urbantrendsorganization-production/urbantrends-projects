/**
 * Turning the report's numbers into the strings the screen prints.
 *
 * The API sends rates as fractions or as **null**, and the null is never zero —
 * a stylist with no rostered hours is absent, not idle; a shop with no finished
 * bookings has an unknown no-show rate, not a perfect one. Every formatter here
 * therefore has a "we do not know" branch, and it prints an em dash rather than
 * a number. A dashboard that renders `null` as `0 %` is the most flattering
 * possible lie to tell a shop on its first week.
 */

/** `7.1 %`, or `—` when the denominator was zero. */
export function percent(fraction: number | null, places = 1): string {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return "—";
  return `${(fraction * 100).toFixed(places)} %`;
}

/** For a bar's width. Unknown collapses to nothing rather than to a full bar. */
export function barWidth(fraction: number | null): string {
  if (fraction === null || fraction === undefined) return "0%";
  return `${Math.min(100, Math.max(0, fraction * 100)).toFixed(1)}%`;
}

/** `3 hr 20 min` of chair time. */
export function hours(minutes: number): string {
  const whole = Math.round(minutes / 60);
  return whole === 1 ? "1 hr" : `${whole} hr`;
}

/**
 * The direction a rate moved, as a word rather than an arrow glyph. The design
 * ships no icon font and the handoff's arrows are placeholders.
 */
export function movement(now: number | null, before: number | null): "down" | "up" | "flat" | null {
  if (now === null || before === null) return null;
  const points = (now - before) * 100;
  if (points < -0.5) return "down";
  if (points > 0.5) return "up";
  return "flat";
}

/** `4 Jun – 13 Jun 2026`. The comparison period is printed next to it, so the
 *  reader can see it is the shop's own past and not a pre-BookNasi baseline. */
export function range(startsOn: string, endsOn: string): string {
  const from = new Date(`${startsOn}T00:00:00+03:00`);
  const to = new Date(`${endsOn}T00:00:00+03:00`);
  const day = (d: Date, withYear: boolean) =>
    d.toLocaleDateString("en-GB", {
      timeZone: "Africa/Nairobi",
      day: "numeric",
      month: "short",
      ...(withYear ? { year: "numeric" } : {}),
    });
  return `${day(from, from.getFullYear() !== to.getFullYear())} – ${day(to, true)}`;
}
