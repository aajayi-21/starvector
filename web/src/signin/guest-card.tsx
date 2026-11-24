/**
 * The guest gate (spec IM1 §7.2 and §16): one card with the notice,
 * the proof of work, and `I agree`. It makes a guest, and a cookie of
 * this browser is then the identity. No name and no password.
 *
 * The notice comes first because each instant trial is public (spec
 * IM1 ruling 6). The proof starts when the card opens, so it is done
 * when the person has read the notice.
 */

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { useApi } from "../api/client";
import { ApiError, friendlyMessage } from "../api/types";
import { NoticeText } from "./notice-text";
import { ProofField } from "./proof-field";

export function GuestCard(props: {
  /** The guest is made: the shell reads the identity again. */
  onDone: () => void;
  /** Back to the ways in with an account. */
  onBack: () => void;
}): React.JSX.Element {
  const api = useApi();
  const [proof, setProof] = useState<string | undefined>(undefined);
  const [proofRound, setProofRound] = useState(0);
  const make = useMutation({
    mutationFn: () => api.makeGuest(true, proof),
    onSuccess: props.onDone,
    onError: (error) => {
      // A proof that ran out or was spent: the widget starts again.
      if (error instanceof ApiError && error.refusalCause === "proof") {
        setProof(undefined);
        setProofRound((round) => round + 1);
      }
    },
  });
  return (
    <section className="gate-card" aria-label="Play as a guest">
      <h2>Try an instant trial</h2>
      <p className="muted">
        No account needed. You sketch, a photo is picked a few seconds after you
        send, and you see how close you came.
      </p>
      <NoticeText />
      <ProofField
        key={proofRound}
        challengeUrl={api.guestChallengeUrl()}
        onProof={setProof}
      />
      <div className="row">
        <button
          type="button"
          className="btn btn-primary"
          disabled={proof === undefined || make.isPending}
          onClick={() => make.mutate()}
        >
          {make.isPending ? "One moment…" : "I agree"}
        </button>
        <button type="button" className="btn btn-ghost" onClick={props.onBack}>
          Back
        </button>
      </div>
      {make.isError ? (
        <div className="notice notice-bad" role="alert">
          {friendlyMessage(make.error)}
        </div>
      ) : null}
    </section>
  );
}
