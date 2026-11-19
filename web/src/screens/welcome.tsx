/**
 * The signed-out gate screen (spec A2 §3, on the landing page of spec
 * BR1 §6). It renders on a 401 and on nothing else: a server that is
 * down is ApiError(0), and showing that reader a sign-in form sends
 * them somewhere no password helps.
 *
 * The ways in, each typed on this device and each in the one gate
 * card (`signin/gate-card.tsx`):
 * - a username and a password (`Sign in`);
 * - a new account (`Create an account`), when the server makes them;
 * - a recovery code (`Forgot it?` at the password);
 * - a device code from a device that is signed in — the path with no
 *   password to type (spec A2 §3.5);
 * - on a dev server, the open door (spec A1 §4).
 *
 * A sign-up and a recovery answer with a recovery code. The screen
 * shows it one time and reads `me` again only after the player clicks
 * `I've saved my code`, thus the app does not replace the code before
 * the player has it.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useApi } from "../api/client";
import { isRefusal } from "../api/types";
import { GateCard } from "../signin/gate-card";
import { RecoveryCodeStep } from "../signin/recovery-code-step";
import { SignupProgress } from "../signin/signup-progress";
import { LogoMark } from "../ui/logo";
import { isPostClose } from "../ui/pick-copy";
import { HowItWorksSteps, Premise } from "./how";

/** The query keys this screen reads with no session. */
const GATE_READS: ReadonlySet<string> = new Set(["about", "door", "signup"]);

/** A recovery code that waits for its `I've saved my code` click. */
interface ShownCode {
  code: string;
  /** True after a recovery: the earlier code is dead. */
  replaces: boolean;
}

export function WelcomeScreen(): React.JSX.Element {
  const api = useApi();
  const queryClient = useQueryClient();
  const about = useQuery({
    queryKey: ["about"],
    queryFn: () => api.getAbout(),
    staleTime: Number.POSITIVE_INFINITY,
  });
  const postClose = isPostClose(about.data?.pick_protocol);
  const door = useQuery({
    queryKey: ["door"],
    queryFn: () => api.getDoor(),
    retry: false,
  });
  // Read one time (spec A2 §8): the constant 404 means no sign-up.
  const signup = useQuery({
    queryKey: ["signup"],
    queryFn: () => api.getSignup(),
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const [shown, setShown] = useState<ShownCode | null>(null);
  // The cookie came with the answer. Each query of the app starts
  // again, thus the shell reads me and renders signed in, and no
  // screen shows a cached answer of an account that was signed in
  // here before. The gate's own reads hold no player's data and stay:
  // the sign-up switch is read one time (spec A2 §8).
  const enter = () =>
    void queryClient.resetQueries({
      predicate: (query) => !GATE_READS.has(String(query.queryKey[0])),
    });
  const photoCount = about.data?.photo_count;
  return (
    <>
      <header className="topbar">
        <span className="brand">
          <LogoMark />
          Starvector
        </span>
      </header>
      <main className="page">
        {/* Three parts in the page flow: the headline, sign-in, and how
            it works. On a phone they stack in that sequence, thus the
            form is the first card and a home-screen app that opens
            signed out meets it at once. On a wide screen the grid puts
            sign-in in the right column, level with the headline, and
            how it works below the headline (app.css .welcome-grid). */}
        <div className="welcome-grid">
          <div className="welcome-hero">
            <h1 className="welcome-title">
              {postClose
                ? "A new photo every day."
                : "A new hidden photo every day."}
            </h1>
            {about.data?.test_season === true ? (
              <p className="welcome-season" role="note">
                <span className="badge badge-warn">Test season</span>
                <span className="hint">
                  Results won't carry over to the public launch.
                </span>
              </p>
            ) : null}
            <p className="welcome-pitch muted">
              {postClose
                ? "Each day a photo is picked at random after the day closes, and nobody knows it while you play."
                : "Each day a photo is hidden behind a short code."}{" "}
              You sketch and describe whatever comes to mind, and when the day
              closes you see the photo — and how close you came
              {photoCount === undefined
                ? "."
                : `, measured against ${photoCount} photos.`}
            </p>
          </div>
          <div className="stack welcome-signin">
            {shown === null ? (
              <GateCard
                signupOpen={signup.data?.open === true}
                signupClosed={isRefusal(signup.error)}
                noticeVersion={signup.data?.notice_version}
                doorOpen={door.data?.open === true}
                onSignedIn={enter}
                onRecoveryCode={(code, replaces) =>
                  setShown({ code, replaces })
                }
              />
            ) : (
              <>
                {/* A sign-up is at its second part; a recovery has no
                    parts to show. */}
                {shown.replaces ? null : <SignupProgress current={2} />}
                <div className="card card-hero">
                  <RecoveryCodeStep
                    code={shown.code}
                    replaces={shown.replaces}
                    onDone={enter}
                  />
                </div>
              </>
            )}
          </div>
          <section className="welcome-how" aria-labelledby="how-heading">
            <h2 id="how-heading">How it works</h2>
            <Premise />
            <HowItWorksSteps protocol={about.data?.pick_protocol} />
          </section>
        </div>
      </main>
    </>
  );
}
