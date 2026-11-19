/**
 * The Releases page (spec F1 §3): where the downloads will be. A
 * signed-out browser can open it. It is a placeholder: the owner sets
 * up the page, and until then it says that there is nothing to
 * download.
 */

export function ReleasesScreen(): React.JSX.Element {
  return (
    <div className="page-narrow stack-lg" style={{ margin: "0 auto" }}>
      <div className="page-header">
        <h1>Releases</h1>
        <p className="muted">Downloads of Starvector, newest first.</p>
      </div>
      <section className="card">
        <p className="muted">No releases to download yet.</p>
      </section>
    </div>
  );
}
