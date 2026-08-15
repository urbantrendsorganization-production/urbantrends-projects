/**
 * `/` — the two doors, and nothing else.
 *
 * This was a slice-1 placeholder reading "screens start in slice 4" until slice
 * 11, which is roughly when somebody would first have typed the bare domain in
 * and found a note to themselves.
 *
 * Deliberately not a marketing page. There is no product copy here because the
 * product's real front door is a shop's booking link arriving over WhatsApp —
 * a client never sees this route, and an owner sees it once. What it owes them
 * is a way in, and the honest statement of what the two ways are.
 */

const CARD: React.CSSProperties = {
  display: "grid",
  gap: "var(--bn-space-3)",
  padding: "var(--bn-space-9) var(--bn-space-7)",
  borderRadius: "var(--bn-radius-card)",
  background: "var(--bn-surface)",
  border: "1.5px solid var(--bn-border)",
  color: "var(--bn-ink)",
  textDecoration: "none",
  // CLAUDE.md §10, invariant 1. These are links rather than buttons and the
  // floor applies just the same — it is about thumbs, not about elements.
  minHeight: 52,
};

export default function Home() {
  return (
    <main
      style={{
        maxWidth: 420,
        margin: "0 auto",
        minHeight: "100vh",
        padding: "var(--bn-space-11) var(--bn-space-gutter)",
        background: "var(--bn-canvas)",
        display: "grid",
        alignContent: "start",
        gap: "var(--bn-space-9)",
      }}
    >
      <header style={{ display: "grid", gap: "var(--bn-space-4)" }}>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--bn-font-display)",
            fontSize: "var(--bn-text-display-size)",
            lineHeight: "var(--bn-text-display-leading)",
            letterSpacing: "var(--bn-text-display-tracking)",
          }}
        >
          BookNasi
        </h1>
        <p style={{ margin: 0, color: "var(--bn-ink-70)", textWrap: "pretty" }}>
          Appointments and M-Pesa deposits for salons and barbershops.
        </p>
      </header>

      <nav style={{ display: "grid", gap: "var(--bn-space-6)" }}>
        <a href="/signin" style={CARD}>
          <strong style={{ fontSize: "var(--bn-text-body-lg-size)" }}>Sign in</strong>
          <span style={{ color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
            Owners, managers and staff.
          </span>
        </a>
        <a href="/signup" style={CARD}>
          <strong style={{ fontSize: "var(--bn-text-body-lg-size)" }}>Set up a shop</strong>
          <span style={{ color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
            About eight minutes, and you can take bookings before the end.
          </span>
        </a>
      </nav>

      <p style={{ margin: 0, color: "var(--bn-ink-45)", fontSize: "var(--bn-text-body-sm-size)" }}>
        Booking an appointment? Use the link your shop sent you — there is no account to make.
      </p>
    </main>
  );
}
