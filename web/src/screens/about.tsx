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
  "Hi everyone!",
  "I created Starvector as both a way for people to experiment with remote viewing in a fun/competitive and a way to gather high quality, modern remote viewing data for public research.",
  "I recently learned about remote viewing and was interested in finding a way to test it's claim rigorously. I believe that modern ML methods can give us an unbiased judge on the accuracy of sketches to their target. Of course, applying this needs data, and that's where Starvector comes in!",
  "For anyone who's tried remote viewing before, you'll know it's very fun and the rush you get when you get a hit is amazing. Remote viewing is also a skill that anyone can develop. This is why I thought that turning remote viewing into a fun and competitive game is the best avenue for acquiring high quality data.",
  "Methodologically, Starvector uses a curated set of images as the set of possible targets. The targets are randomly selected (with a drand beacon to verify randomness!) with their precalculated multimodal vector embedding. Then, the user sketch submitted and embedded. These vector embeddings are compared and a score is calculated based on their similarity. This is a very high level explanation, there are more intermediate steps (removing centroids from the image pool to prevent reward hacking, pre-processing images so their comparable to a sketch, LLM judges, etc.) Read the code for more details!",
  "I plan on routinely releasing a public, datasets of user responses which can be programmatically queried (e.g. SQL). This is primarily interested for people to empirically test if remote viewing is real.",
  "Respecting user privacy and utilizing FOSS tooling was also something very important to me. The website takes no user data and no email is needed to sign up! No cookies are used and all of your responses are anonymous (unless you choose to put your actual identity for whatever reason). ",
  "Feel free to open up PRs or Issues and I will review them. I'm also open to collaborating with anyone that has ideas on how to improve Starvector, do remote viewing research, or possibly help fund the endeavor. ",
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
