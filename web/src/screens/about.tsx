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
    <div className="page-narrow text-page">
      <div className="page-header">
        <h1>About Starvector</h1>
      </div>
      <section>
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
        {/* The author credit that the NOTICE file's section 7(b) term asks
            each copy to keep somewhere public. */}
        <p className="muted small">
          Starvector by Adeolu Ajayi. Free software under the GNU AGPL, version
          3.
        </p>
      </section>
    </div>
  );
}
