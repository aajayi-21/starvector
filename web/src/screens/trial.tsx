/**
 * The public page of one instant trial (spec IM1 §10), at
 * `/t/<date>/<trial_id>`. Each browser can open it, with no session.
 *
 * It shows the sketch adjacent to the photo, the result, and the record
 * of the owner: `trial 37 of 50` and the mean of all of them. That line
 * is the defense against a selected result, so it stands with the
 * result and not below a fold. The page holds no word of the send
 * (spec SS1 ruling 2): the words are in the public database.
 *
 * The last part is the check: the pulse, the pick facts, and the
 * command that a reader runs on a saved copy of the answer.
 */

import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";

import { useApi } from "../api/client";
import type { PublicTrial } from "../api/types";
import { friendlyMessage, isRefusal } from "../api/types";
import { ChanceMeter } from "../ui/chance-meter";
import { ordinal, percentBeaten } from "../ui/format";
import { SketchThumb } from "../ui/sketch-thumb";
import { Credit } from "./reveal";

export function TrialScreen(): React.JSX.Element {
  const api = useApi();
  const { date, trialId } = useParams({ from: "/t/$date/$trialId" });
  const trial = useQuery({
    queryKey: ["public-trial", date, trialId],
    queryFn: () => api.getPublicTrial(date, trialId),
    retry: false,
  });
  if (trial.isPending) {
    return (
      <p className="subtle" aria-busy="true">
        Loading…
      </p>
    );
  }
  if (trial.isError || trial.data === undefined) {
    return (
      <section className="trial-page">
        <h1>Instant trial</h1>
        {isRefusal(trial.error) ? (
          <p className="muted">
            This trial has no public page. It may still be waiting for its
            photo, or the address may be wrong.
          </p>
        ) : (
          <div className="notice notice-bad" role="alert">
            {friendlyMessage(trial.error)}
          </div>
        )}
        <TryIt />
      </section>
    );
  }
  return <TrialPage trial={trial.data} />;
}

function TryIt(): React.JSX.Element {
  return (
    <p>
      <Link to="/instant" className="btn btn-secondary">
        Try an instant trial
      </Link>
    </p>
  );
}

/** Who made the trial, as the page names them. */
function ownerName(trial: PublicTrial): string {
  if (trial.kind === "guest") {
    return "a guest";
  }
  return trial.named ? trial.owner : "a player who left";
}

function TrialPage(props: { trial: PublicTrial }): React.JSX.Element {
  const api = useApi();
  const { trial } = props;
  const score = trial.trial;
  const who = ownerName(trial);
  const sent = new Date(trial.received_at);
  return (
    <article className="trial-page">
      <header className="trial-head">
        <p className="kicker">Instant trial</p>
        <h1>
          {percentBeaten(score.p)}% by {who}
        </h1>
        <p className="muted">
          Sent{" "}
          <time dateTime={trial.received_at}>
            {sent.toLocaleString(undefined, {
              dateStyle: "medium",
              timeStyle: "short",
            })}
          </time>
          . The photo was picked a few seconds after the send, by a public
          random number that did not exist before it.
        </p>
      </header>

      <div className="trial-pair">
        <figure className="trial-sketch">
          {trial.state === "sketch" ? (
            <SketchThumb
              strokes={trial.strokes}
              label={`The sketch of ${who}`}
            />
          ) : (
            <p className="trial-mark" role="note">
              {trial.state === "withheld"
                ? "The sketch of this trial is withheld."
                : "This trial was sent with words only."}
            </p>
          )}
          <figcaption className="subtle tiny">
            The sketch
            {trial.words > 0
              ? `, sent with ${trial.words} ${trial.words === 1 ? "typed line" : "typed lines"} that this page does not show`
              : ""}
          </figcaption>
        </figure>
        <figure className="trial-photo">
          <div className="picture-frame">
            <img
              src={api.imageUrl(trial.target_id)}
              alt={trial.credit?.title ?? "The photo of this instant trial"}
            />
          </div>
          <figcaption>
            <Credit credit={trial.credit} />
          </figcaption>
        </figure>
      </div>

      <section className="trial-result" aria-label="Result">
        <p>
          The sketch matched this photo better than {score.beaten} of the other{" "}
          {score.decoy_count} photos. It was the {ordinal(score.target_rank)}
          -closest match.
        </p>
        <ChanceMeter p={score.p} />
        <RecordLine trial={trial} who={who} />
      </section>

      <TrialCheck trial={trial} />
      <TryIt />
    </article>
  );
}

/**
 * The record of the owner (spec IM1 §9 and §10): this trial among all
 * of them. One good trial of many reads as what it is.
 */
function RecordLine(props: {
  trial: PublicTrial;
  who: string;
}): React.JSX.Element {
  const { record } = props.trial;
  const waiting = record.sent - record.settled;
  return (
    <p className="trial-record" role="note">
      <strong>
        Trial {record.position} of {record.sent}
      </strong>{" "}
      by {props.who}.{" "}
      {record.mean_p === null
        ? ""
        : `The average of ${record.settled === 1 ? "the one" : `all ${record.settled}`} with a result is ${percentBeaten(record.mean_p)}%. `}
      {waiting > 0 ? `${waiting} more wait for a photo. ` : ""}
      Chance is 50%, and no trial can be removed from this record.
    </p>
  );
}

function saveCheckFile(trial: PublicTrial): void {
  const text = `${JSON.stringify(trial, null, 2)}\n`;
  const blob = new Blob([text], { type: "application/json" });
  const address = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = address;
  anchor.download = "trial.json";
  anchor.click();
  URL.revokeObjectURL(address);
}

/** The pick of the photo, and how a reader checks it (spec IM1 §10). */
function TrialCheck(props: { trial: PublicTrial }): React.JSX.Element {
  const { trial } = props;
  const pick = trial.pick;
  const publicBeacon = pick.beacon_chain === "drand-quicknet";
  const pulseAddress = `https://api.drand.sh/${pick.beacon_chain_hash}/public/${pick.beacon_round}`;
  return (
    <details className="trial-check">
      <summary>How the photo was picked, and how to check it</summary>
      {publicBeacon ? null : (
        <div className="notice notice-warn" role="note">
          This trial used a test beacon, not the public one, so its pick proves
          nothing.
        </div>
      )}
      <dl className="fact-list">
        <dt>Beacon pulse</dt>
        <dd>
          {publicBeacon ? (
            <a href={pulseAddress} target="_blank" rel="noreferrer">
              {pick.beacon_round}
            </a>
          ) : (
            pick.beacon_round
          )}
          , after the send
        </dd>
        <dt>Position in the set of {pick.pool_count} photos</dt>
        <dd>{pick.target_index}</dd>
        <dt>Randomness of the pulse</dt>
        <dd className="mono-wrap">{pick.randomness}</dd>
        <dt>Digest of the send</dt>
        <dd className="mono-wrap">{pick.send_digest}</dd>
        <dt>Server value, committed before the pulse</dt>
        <dd className="mono-wrap">{pick.nonce}</dd>
        <dt>Fingerprint of the set of photos</dt>
        <dd className="mono-wrap">{pick.pool_root}</dd>
      </dl>
      <p className="muted small">
        Save this page's data as <code>trial.json</code>, then run the check
        from the source code:
      </p>
      <pre className="trial-command">
        <code>{trial.check}</code>
      </pre>
      <div>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => saveCheckFile(trial)}
        >
          Save trial.json
        </button>
      </div>
    </details>
  );
}
