/**
 * The proof of work on the sign-up form (spec PW1 §4). The ALTCHA
 * widget reads a challenge the server signed and solves it in a web
 * worker. It starts when the form opens, so the work runs while the
 * person types a name and a password. The form sends the payload with
 * them, and `Create account` stays disabled until the widget is done.
 *
 * The widget records no pointer, scroll, or key timing, and it shows
 * its small attribution to altcha.org (spec PW1 decision D9). The mock
 * world has no server to sign a challenge, so it shows no widget and
 * gives a fixed payload.
 */

import { useEffect, useRef, useState } from "react";

import { useApi } from "../api/client";
import { loadAltcha } from "./altcha-load";

/** The payload of the mock world, which its `signUp` accepts. */
export const MOCK_PROOF = "mock-proof";

const CONFIGURATION = JSON.stringify({
  humanInteractionSignature: false,
});

type StateDetail = { state: string; payload?: string };

export function ProofField(props: {
  /** The payload when the widget is done; `undefined` until then. */
  onProof: (payload: string | undefined) => void;
  /**
   * Where the widget reads its challenge. With none given, it is the
   * challenge of the sign-up form. The guest gate gives its own (spec
   * IM1 §7.2). `null` is the mock world.
   */
  challengeUrl?: string | null;
}): React.JSX.Element | null {
  const api = useApi();
  const challengeUrl =
    props.challengeUrl === undefined
      ? api.signupChallengeUrl()
      : props.challengeUrl;
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const widget = useRef<HTMLElement>(null);
  // The latest callback, so the listener below needs no new binding
  // each time the form renders.
  const onProof = useRef(props.onProof);
  onProof.current = props.onProof;

  useEffect(() => {
    if (challengeUrl === null) {
      onProof.current(MOCK_PROOF);
      return;
    }
    let live = true;
    loadAltcha().then(
      () => live && setLoaded(true),
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
  }, [challengeUrl]);

  useEffect(() => {
    const element = widget.current;
    if (!loaded || element === null) {
      return;
    }
    const onState = (event: Event) => {
      const detail = (event as CustomEvent<StateDetail>).detail;
      // An expired or failed check takes the payload away again.
      onProof.current(detail.state === "verified" ? detail.payload : undefined);
    };
    element.addEventListener("statechange", onState);
    return () => element.removeEventListener("statechange", onState);
  }, [loaded]);

  if (challengeUrl === null) {
    return null;
  }
  if (failed) {
    return (
      <div className="notice notice-bad" role="alert">
        The check that you're a person didn't load. Reload the page and try
        again.
      </div>
    );
  }
  return (
    <div className="proof-field" aria-busy={!loaded}>
      {loaded ? (
        <altcha-widget
          ref={widget}
          challenge={challengeUrl}
          auto="onload"
          name="proof"
          configuration={CONFIGURATION}
        />
      ) : null}
    </div>
  );
}
