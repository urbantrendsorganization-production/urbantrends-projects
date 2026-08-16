"use client";

/**
 * "Is my booking page live yet, and if not, why not?"
 *
 * The answer is computed in `shops/readiness.py` and only worded here — the
 * same split as the dashboard's verdict (CLAUDE.md §12), and for the same
 * reason. The rule for "bookable" is the availability engine's composition
 * rule, and §4 allows exactly one implementation of it.
 *
 * ## It is a list, not a wizard
 *
 * A wizard is a thing you see once. The design's onboarding is four ordered
 * steps, but the ordering is the useful part, not the modality: a shop adds a
 * stylist in March and needs the same list to tell it the new person is
 * rostered but has no services ticked. So the order is kept and the one-way
 * door is not, and a returning owner sees the same screen with everything
 * ticked instead of a flow they cannot re-enter.
 *
 * ## Every outstanding item is a link to the thing that fixes it
 *
 * The server names a section, never a URL (see `Check.action` there). A
 * checklist that says what is wrong and leaves the owner to find the form is
 * the same screen as no checklist.
 */

export type Check = {
  key: string;
  done: boolean;
  title: string;
  detail: string;
  action: string;
};

export type Readiness = {
  shop_id: string;
  is_bookable: boolean;
  booking_url: string;
  checks: Check[];
  deposit_free_services: { id: string; name: string }[];
};

/**
 * The tick or bullet beside each row.
 *
 * `aria-hidden`, and the size lives here rather than in a shared style object
 * so the two are readable together: it is decoration, the row's own text
 * already says whether the item is done, and it is not reachable by anyone.
 * `check-invariants.mjs` looks for exactly that attribute next to a height
 * below the floor, which is the right thing for it to insist on.
 */
function Dot({ done }: { done: boolean }) {
  return (
    <span
      aria-hidden="true"
      style={{
        width: 22,
        height: 22,
        borderRadius: "var(--bn-radius-pill)",
        display: "grid",
        placeItems: "center",
        flexShrink: 0,
        fontSize: 13,
        fontWeight: 700,
        background: done ? "var(--bn-pay-50)" : "var(--bn-hold-50)",
        color: done ? "var(--bn-pay-700)" : "var(--bn-hold-700)",
      }}
    >
      {done ? "✓" : "•"}
    </span>
  );
}

export function Checklist({
  readiness,
  onGo,
  reachable,
}: {
  readiness: Readiness;
  onGo: (section: string) => void;
  /**
   * Sections this person can actually open. Omit for "all of them".
   *
   * Added at slice 13, because M-Pesa is the first check whose fix is behind a
   * role the reader may not have: a manager sees "Connect your M-Pesa"
   * outstanding and there is no tab for it. A Fix button that silently blanks
   * the screen is worse than the honest sentence, and hiding the row entirely
   * would be worse still — the shop genuinely is not bookable, and a checklist
   * that reports it as fine because of who is looking is a checklist that lies.
   */
  reachable?: string[];
}) {
  const outstanding = readiness.checks.filter((check) => !check.done);

  return (
    <section
      style={{
        border: "1px solid var(--bn-line)",
        borderRadius: "var(--bn-radius-card)",
        background: "var(--bn-surface)",
        overflow: "hidden",
      }}
    >
      <Banner readiness={readiness} outstanding={outstanding.length} />

      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {readiness.checks.map((check) => (
          <li
            key={check.key}
            style={{
              display: "flex",
              gap: "var(--bn-space-6)",
              alignItems: "center",
              padding: "var(--bn-space-6) var(--bn-space-8)",
              borderTop: "1px solid var(--bn-line)",
            }}
          >
            <Dot done={check.done} />
            <span style={{ display: "grid", gap: "var(--bn-space-2)", flex: 1, minWidth: 0 }}>
              <span
                style={{
                  color: check.done ? "var(--bn-ink-45)" : "var(--bn-ink)",
                  fontWeight: check.done ? 400 : 600,
                }}
              >
                {check.title}
              </span>
              <span
                style={{
                  color: "var(--bn-ink-70)",
                  fontSize: "var(--bn-text-body-sm-size)",
                  textWrap: "pretty",
                }}
              >
                {check.detail}
              </span>
            </span>
            {/*
              Only what is outstanding gets a button. A "Done ✓" row with a
              link beside it reads as an action still to take, and the list's
              whole job is to be scannable for what is left.
            */}
            {check.done ? (
              <span
                style={{ color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}
              >
                Done
              </span>
            ) : reachable && !reachable.includes(check.action) ? (
              <span
                style={{
                  color: "var(--bn-ink-45)",
                  fontSize: "var(--bn-text-body-sm-size)",
                  textAlign: "right",
                  flexShrink: 0,
                  maxWidth: "12em",
                }}
              >
                Ask the owner
              </span>
            ) : (
              <button
                type="button"
                onClick={() => onGo(check.action)}
                style={{
                  minHeight: "var(--bn-target-control)",
                  padding: "0 var(--bn-space-7)",
                  borderRadius: "var(--bn-radius-md)",
                  border: "1.5px solid var(--bn-border)",
                  background: "var(--bn-surface)",
                  color: "var(--bn-ink)",
                  fontFamily: "var(--bn-font-ui)",
                  fontSize: "var(--bn-text-body-size)",
                  fontWeight: 600,
                  cursor: "pointer",
                  flexShrink: 0,
                }}
              >
                Fix
              </button>
            )}
          </li>
        ))}
      </ul>

      {readiness.deposit_free_services.length ? (
        <p
          style={{
            margin: 0,
            borderTop: "1px solid var(--bn-line)",
            padding: "var(--bn-space-6) var(--bn-space-8)",
            background: "var(--bn-canvas)",
            color: "var(--bn-ink-70)",
            fontSize: "var(--bn-text-body-sm-size)",
            textWrap: "pretty",
          }}
        >
          Bookable by staff but not online, because they take no deposit:{" "}
          <strong style={{ color: "var(--bn-ink)" }}>
            {readiness.deposit_free_services.map((service) => service.name).join(", ")}
          </strong>
          .
        </p>
      ) : null}
    </section>
  );
}

/**
 * The banner states the conclusion, and the conclusion is a fact rather than a
 * judgement — "your booking page is live" is checkable, unlike the dashboard's
 * verdict, which is why this one is safe to word on the client.
 */
function Banner({ readiness, outstanding }: { readiness: Readiness; outstanding: number }) {
  const live = readiness.is_bookable;
  return (
    <header
      style={{
        padding: "var(--bn-space-8)",
        background: live ? "var(--bn-pay-50)" : "var(--bn-canvas)",
        display: "grid",
        gap: "var(--bn-space-4)",
      }}
    >
      <h2
        style={{
          margin: 0,
          fontFamily: "var(--bn-font-display)",
          fontSize: "var(--bn-text-title-size)",
          color: live ? "var(--bn-pay-700)" : "var(--bn-ink)",
        }}
      >
        {live
          ? "Your booking page is live"
          : `${outstanding} ${outstanding === 1 ? "thing" : "things"} left before clients can book`}
      </h2>
      <p style={{ margin: 0, color: "var(--bn-ink-70)", textWrap: "pretty" }}>
        {live ? (
          <>
            Send clients to{" "}
            <a
              href={readiness.booking_url}
              style={{ color: "var(--bn-accent)", fontFamily: "var(--bn-font-mono)" }}
            >
              {readiness.booking_url.replace(/^https:\/\//, "")}
            </a>
            . It is the link to paste into WhatsApp and your Instagram bio.
          </>
        ) : (
          <>
            Until then the page at{" "}
            <span style={{ fontFamily: "var(--bn-font-mono)" }}>
              {readiness.booking_url.replace(/^https:\/\//, "")}
            </span>{" "}
            loads and offers no times. Staff can still book and record walk-ins.
          </>
        )}
      </p>
    </header>
  );
}
