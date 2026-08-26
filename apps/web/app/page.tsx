// Phase 0 ships one page so the toolchain is proven end to end.
// The four real surfaces -- chat, dashboard, exception explorer, provenance
// drawer -- arrive in Phase 9, after the trust layer exists.

export default function Home() {
  return (
    <main
      style={{
        fontFamily: "ui-sans-serif, system-ui, sans-serif",
        maxWidth: "42rem",
        margin: "4rem auto",
        padding: "0 1.5rem",
        lineHeight: 1.6,
      }}
    >
      <h1 style={{ fontSize: "1.75rem", margin: 0 }}>RazorMind</h1>
      <p style={{ color: "#555" }}>
        Agentic financial computation &amp; reconciliation.
      </p>
      <p>
        Phase 0 &mdash; foundations. The deterministic core is built and proven
        before anything non-deterministic touches it.
      </p>
    </main>
  );
}
