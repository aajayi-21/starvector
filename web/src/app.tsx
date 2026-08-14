import primaryMark from "./brand/starvector-logo-v2.svg";
import navMark from "./brand/starvector-logo-v2-nav.svg";

/** C1 token smoke page — replaced by the router shell in C5. */
export function App() {
  const ramps = ["neutral", "accent", "accent-2"] as const;
  const steps = [100, 200, 300, 400, 500, 600, 700, 800, 900];
  return (
    <div
      style={{ padding: 28, display: "flex", flexDirection: "column", gap: 24 }}
    >
      <nav
        className="nav"
        style={{ borderBottom: "1px solid var(--color-divider)" }}
      >
        <span
          className="nav-brand"
          style={{ display: "flex", alignItems: "center", gap: 10 }}
        >
          <img src={navMark} width={18} height={18} alt="" />
          Starvector
        </span>
        <span className="tag tag-accent">token smoke page</span>
      </nav>
      <div style={{ display: "flex", gap: 24, alignItems: "center" }}>
        <img src={primaryMark} width={96} height={96} alt="Starvector mark" />
        <div>
          <h2>Nocturne tokens</h2>
          <p className="text-muted">
            Vendored 2026-08-14 retune. Inter 400/500/600/700 self-hosted.
          </p>
        </div>
      </div>
      {ramps.map((ramp) => (
        <div
          key={ramp}
          style={{ display: "flex", gap: 6, alignItems: "center" }}
        >
          <span style={{ width: 90, fontSize: 12 }} className="text-muted">
            {ramp}
          </span>
          {steps.map((step) => (
            <span
              key={step}
              title={`--color-${ramp}-${step}`}
              style={{
                width: 34,
                height: 34,
                borderRadius: 6,
                background: `var(--color-${ramp}-${step})`,
              }}
            />
          ))}
        </div>
      ))}
      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" className="btn btn-primary">
          Primary
        </button>
        <button type="button" className="btn btn-secondary">
          Secondary
        </button>
        <button type="button" className="btn btn-ghost">
          Ghost
        </button>
        <span className="tag tag-outline">Open</span>
        <span className="tag tag-neutral">neutral</span>
      </div>
    </div>
  );
}
