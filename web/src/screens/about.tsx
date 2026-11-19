/**
 * The About page (spec F1 §3). A signed-out browser can open it: it
 * holds fixed text alone.
 *
 * The owner writes the text. Edit ABOUT_PARAGRAPHS below: one string
 * for each paragraph. Nothing else on the page needs a change.
 */

import { GITHUB_URL } from "../ui/site-links";

/** The blurb, one string for each paragraph. A placeholder for now. */
export const ABOUT_PARAGRAPHS: ReadonlyArray<string> = [
  "A few words about Starvector will be here soon.",
];

export function AboutScreen(): React.JSX.Element {
  return (
    <div className="page-narrow stack-lg" style={{ margin: "0 auto" }}>
      <div className="page-header">
        <h1>About Starvector</h1>
      </div>
      <section className="card stack">
        {ABOUT_PARAGRAPHS.map((paragraph) => (
          <p key={paragraph}>{paragraph}</p>
        ))}
        <p className="muted small">
          The source is public.{" "}
          <a href={GITHUB_URL} target="_blank" rel="noreferrer">
            Read the code on GitHub
          </a>
          .
        </p>
      </section>
    </div>
  );
}
