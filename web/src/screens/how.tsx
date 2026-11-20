/**
 * How it works (spec BR1 §6): the game in plain words. Each sentence
 * here is a claim about the scoring, so each one says what the
 * system does and no more — the result is a rank among the photos,
 * 50% is what guessing averages, and practice stores nothing. The
 * premise is stated as a question, because the game tests it and does
 * not assume an answer (spec PL1 §8).
 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { useApi } from "../api/client";
import type { PickProtocol } from "../api/types";
import { localTimeOfUtc } from "../ui/format";
import { isPostClose, photoNoun } from "../ui/pick-copy";

/** The premise, in one place: each how-it-works surface shows this. */
export function Premise(): React.JSX.Element {
  return (
    <p>
      Starvector tests one question: can a person pick up anything about a photo
      they have never seen? The game doesn't assume they can. With nothing to go
      on, results land at 50% on average, so anything steadily above that is
      worth a closer look.
    </p>
  );
}

export function HowItWorksSteps(props: {
  protocol: PickProtocol | undefined;
}): React.JSX.Element {
  return (
    <ol className="step-list how-steps">
      <li className="step-item">
        <span className="step-icon" aria-hidden="true" />
        <div className="step-text">
          <h3>Start from the code</h3>
          <p className="muted">
            {isPostClose(props.protocol)
              ? "After the day closes, a public random number picks the photo. You describe it before anyone, us included, can know it."
              : "Each day a photo is picked at random and hidden behind a short code. You don't see the photo until the day closes."}
          </p>
        </div>
      </li>
      <li className="step-item">
        <span className="step-icon" aria-hidden="true" />
        <div className="step-text">
          <h3>Sketch and describe</h3>
          <p className="muted">
            Draw on the canvas and add a few words for whatever comes to mind:
            shapes, textures, colors, feelings. There are no wrong answers.
          </p>
        </div>
      </li>
      <li className="step-item">
        <span className="step-icon" aria-hidden="true" />
        <div className="step-text">
          <h3>See how close you came</h3>
          <p className="muted">
            When the day closes, the photo is revealed and your sketch is
            compared with every photo in the set. Guessing lands around 50% on
            average. Above that, you beat chance.
          </p>
        </div>
      </li>
    </ol>
  );
}

export function HowItWorksScreen(): React.JSX.Element {
  const api = useApi();
  const about = useQuery({
    queryKey: ["about"],
    queryFn: () => api.getAbout(),
    staleTime: Number.POSITIVE_INFINITY,
  });
  const photos = about.data?.photo_count;
  const hour = about.data?.closes_at_utc ?? null;
  const protocol = about.data?.pick_protocol;
  const postClose = isPostClose(protocol);
  return (
    <div className="page-narrow text-page">
      <div className="page-header">
        <h1>How Starvector works</h1>
        <p className="muted">
          {postClose ? "One photo a day" : "One hidden photo a day"}, one sketch
          from you, and an honest measure of how close you came.
        </p>
      </div>

      <section>
        <h2>The idea</h2>
        <Premise />
      </section>

      <section>
        <HowItWorksSteps protocol={protocol} />
      </section>

      <section>
        <h2>Your result</h2>
        <p>
          Your sketch and words are compared with each photo in the set
          {photos === undefined ? "" : ` (${photos} photos)`}. Your result is
          the share of the other photos that matched your sketch less closely
          than {postClose ? "the day's photo" : "the hidden one"} did.
        </p>
        <ul className="fact-list">
          <li>100% means {photoNoun(protocol)} was your closest match.</li>
          <li>50% is what random guessing averages.</li>
          <li>One day says little — luck moves single results a lot.</li>
        </ul>
      </section>

      <section>
        <h2>Your skill number</h2>
        <p>
          Over many days your results combine into one number. 1.00 is chance,
          the same thing as averaging 50%. 2.00 is the same as averaging 67%. It
          takes a lot of days before the number settles, so the results page
          also shows how often luck alone would do as well. The leaderboard
          shows a steadied version, which stays near the middle until enough
          results back it, so the two numbers can differ.
        </p>
        <p>
          Beside it sits a hit number. It is also 1.00 at chance, and it rises
          when more of your results land near the very top. The two reward
          different patterns: the skill number a small edge on most days, the
          hit number occasional strong hits. The “how often luck alone would do
          as well” figure checks the two patterns at once, with an allowance for
          checking twice.
        </p>
      </section>

      <section>
        <h2>Days and practice</h2>
        <p>
          You can send once each day, and you can't change it after.
          {hour === null
            ? ""
            : ` A new day starts at ${localTimeOfUtc(hour)} your time, when the last one closes and its photo is revealed.`}
        </p>
        <p>
          In <Link to="/practice">Practice</Link> you can replay past photos, up
          to an hourly limit. Practice results are never saved and never count.
        </p>
      </section>

      <section>
        <h2>Fair play</h2>
        {postClose ? (
          <p>
            No photo is chosen while a day is open, so nobody, us included, can
            know it or leak it. A minute after the close, a pulse of the drand
            public randomness beacon picks it from a set of photos fixed in
            advance. Each results page shows the pulse and a proof under “Check
            that this day was fair”, so anyone can recheck the pick.
          </p>
        ) : (
          <p>
            When a day opens, the server publishes a fingerprint of the hidden
            photo. After the reveal you can check that the fingerprint matches,
            so the photo can't be swapped after you send. Each results page has
            the details under “Check that this day was fair”.
          </p>
        )}
      </section>
    </div>
  );
}
