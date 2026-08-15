/**
 * The one sentence on this screen that states a conclusion.
 *
 * The design asks for a headline that says "Deposits are working" rather than
 * printing a metric, and it is right: an owner should not have to do arithmetic
 * to know whether to renew. It is also the most dangerous string in the
 * product, because it is software making a claim about somebody's business.
 *
 * So the *choice* is the server's — `reporting/metrics.py:verdict_for`, where
 * it is tested against numbers — and only the wording is here. That split is
 * what stops a copy change from quietly becoming a claim change.
 *
 * Every headline is paired with a `support` line that names the evidence, so
 * the conclusion can always be checked against the cards below it. A headline
 * with nothing under it is a slogan.
 */

export type Verdict =
  | "too_early"
  | "no_deposits"
  | "deposits_working"
  | "no_shows_rising"
  | "steady";

type Copy = { headline: string; support: string; tone: "pay" | "fail" | "neutral" };

const COPY: Record<Verdict, Copy> = {
  too_early: {
    headline: "Not enough finished bookings yet",
    support: "Come back once a few more appointments have been completed or missed.",
    tone: "neutral",
  },
  no_deposits: {
    // Deliberately blunt, and deliberately reached before anything
    // encouraging. A shop with every service set to no-deposit is the shop
    // that churns, and the most expensive sentence this product could print is
    // a cheerful one to that shop.
    headline: "You are not taking deposits",
    support: "Nothing was collected in this period, so a no-show costs the full chair.",
    tone: "fail",
  },
  deposits_working: {
    headline: "Deposits are working",
    support: "Fewer clients missed their appointment, and the ones who did left money behind.",
    tone: "pay",
  },
  no_shows_rising: {
    headline: "No-shows are up",
    support: "More clients missed their appointment than in the period before this one.",
    tone: "fail",
  },
  steady: {
    headline: "Holding steady",
    support: "No-shows are about where they were in the period before this one.",
    tone: "neutral",
  },
};

export function headlineFor(verdict: string): Copy {
  return COPY[verdict as Verdict] ?? COPY.steady;
}
