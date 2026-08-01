/**
 * Placeholder. The first real screens land in slice 4 (staff day view) and
 * slice 5 (public booking flow); slice 5 builds them on `packages/booking-core`
 * so that slice 10's widget is a second build target rather than a rewrite.
 */
export default function Home() {
  return (
    <main style={{ padding: "var(--bn-space-9)" }}>
      <h1
        style={{
          fontFamily: "var(--bn-font-display)",
          fontSize: "var(--bn-text-display-size)",
          lineHeight: "var(--bn-text-display-leading)",
          letterSpacing: "var(--bn-text-display-tracking)",
          margin: 0,
        }}
      >
        BookNasi
      </h1>
      <p style={{ color: "var(--bn-ink-45)" }}>
        Foundation slice. Auth and tenancy are live on the API; screens start in slice 4.
      </p>
    </main>
  );
}
