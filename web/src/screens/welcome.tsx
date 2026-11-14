/**
 * The signed-out gate screen (spec A2 §3, on the landing page of spec
 * BR1 §6). It renders on a 401 and on nothing else: a server that is
 * down is ApiError(0), and showing that reader a sign-in form sends
 * them somewhere no password helps.
 *
 * The ways in, each typed on this device:
 * - a username and a password (`Sign in`);
 * - a new account (`Make an account`), when the server makes them;
 * - a recovery code (`I do not have my password`);
 * - a device code from a device that is signed in — the path with no
 *   password to type (spec A2 §3.5).
 *
 * A sign-up and a recovery answer with a recovery code. The screen
 * shows it one time and reads `me` again only after the player clicks
 * `I have my code`, thus the app does not replace the code before the
 * player has it.
 *
 * On a dev server the open door (spec A1 §4) adds a name field.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useApi } from "../api/client";
import { friendlyMessage, isRefusal } from "../api/types";
import { GateCard } from "../signin/gate-card";
import { RecoveryCodeStep } from "../signin/recovery-code-step";
import { LogoMark } from "../ui/logo";
import { HowItWorksSteps, Premise } from "./how";

/** The query keys this screen reads with no session. */
const GATE_READS: ReadonlySet<string> = new Set(["about", "door", "signup"]);

/** A recovery code that waits for its `I have my code` click. */
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
      {about.data?.test_season === true ? (
        <div className="season-note" role="note">
          Test season — results won't carry over to the public launch.
        </div>
      ) : null}
      <main className="page">
        <div className="home-hero" style={{ marginBottom: 40 }}>
          <div className="stack">
            <h1 style={{ fontSize: 36 }}>A new hidden photo every day.</h1>
            <p className="muted" style={{ fontSize: 18, maxWidth: 560 }}>
              Each day a photo is hidden behind a short code. You sketch and
              describe whatever comes to mind, and when the day closes you see
              the photo — and how close you came
              {photoCount === undefined
                ? "."
                : `, measured against ${photoCount} photos.`}
            </p>
          </div>
        </div>
        {/* Sign-in comes first in the page flow: on a phone it is the
            first card, and a home-screen app that opens signed out
            meets the form at once. On a wide screen the grid puts it
            in the right column (app.css .welcome-grid). */}
        <div className="two-columns welcome-grid">
          <div className="stack welcome-signin">
            {shown === null ? (
              <>
                <GateCard
                  signupOpen={signup.data?.open === true}
                  signupClosed={isRefusal(signup.error)}
                  noticeVersion={signup.data?.notice_version}
                  onSignedIn={enter}
                  onRecoveryCode={(code, replaces) =>
                    setShown({ code, replaces })
                  }
                />
                <DeviceCodeCard onSignedIn={enter} />
                {door.data?.open === true ? <DoorCard /> : null}
              </>
            ) : (
              <div className="card card-hero">
                <RecoveryCodeStep
                  code={shown.code}
                  replaces={shown.replaces}
                  onDone={enter}
                />
              </div>
            )}
          </div>
          <section className="card" aria-labelledby="how-heading">
            <h2 id="how-heading">How it works</h2>
            <Premise />
            <HowItWorksSteps />
          </section>
        </div>
      </main>
    </>
  );
}

/**
 * The device code (spec A2 §3.5): a signed-in device makes a code of
 * 8 characters, and this device types it. No password is typed.
 */
function DeviceCodeCard(props: { onSignedIn: () => void }): React.JSX.Element {
  const api = useApi();
  const [code, setCode] = useState("");
  const redeem = useMutation({
    mutationFn: () => api.redeemDeviceCode(code),
    onSuccess: props.onSignedIn,
  });
  const typed = code.replaceAll(/[\s-]/g, "");
  return (
    <section
      className="card card-quiet"
      aria-label="Sign in with a device code"
    >
      <form
        className="stack-sm"
        onSubmit={(event) => {
          event.preventDefault();
          if (typed.length === 8 && !redeem.isPending) {
            redeem.mutate();
          }
        }}
      >
        <label className="label" htmlFor="device-code">
          Signed in on another device?
        </label>
        <p className="hint" id="device-code-hint">
          On that device, open your account and choose “Add a device”. Then type
          the 8-character code here. You don't need your password.
        </p>
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input
            id="device-code"
            className="input"
            aria-describedby="device-code-hint"
            placeholder="ABCD-EFGH"
            autoComplete="one-time-code"
            autoCapitalize="characters"
            spellCheck={false}
            maxLength={12}
            value={code}
            onChange={(event) => setCode(event.target.value)}
            style={{
              fontFamily: "var(--mono)",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
            }}
          />
          <button
            type="submit"
            className="btn btn-secondary"
            disabled={typed.length !== 8 || redeem.isPending}
          >
            {redeem.isPending ? "Signing in…" : "Use this code"}
          </button>
        </div>
        {redeem.isError ? (
          <div className="notice notice-bad" role="alert">
            {friendlyMessage(redeem.error)}
          </div>
        ) : null}
      </form>
    </section>
  );
}

function DoorCard(): React.JSX.Element {
  const api = useApi();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [token, setToken] = useState("");

  const enter = useMutation({
    // No display name: the username is the one name (spec A2 ruling 3).
    mutationFn: () => api.postDoor(name.trim(), undefined, token),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });

  return (
    <section className="card card-quiet" aria-labelledby="door-heading">
      <h3 id="door-heading">Test server sign-in</h3>
      <p className="hint">
        This is a test server, so the operator can sign in with a name and the
        operator token, with no password. Real servers don't show this.
      </p>
      <form
        className="stack-sm"
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim() !== "" && !enter.isPending) {
            enter.mutate();
          }
        }}
      >
        <label className="label" htmlFor="door-name">
          Player name
        </label>
        <input
          id="door-name"
          className="input"
          placeholder="lowercase letters, digits, hyphens"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <label className="label" htmlFor="door-token">
          Operator token
        </label>
        <input
          id="door-token"
          className="input"
          type="password"
          autoComplete="off"
          value={token}
          onChange={(event) => setToken(event.target.value)}
        />
        <button
          type="submit"
          className="btn btn-secondary"
          disabled={name.trim() === "" || enter.isPending}
        >
          {enter.isPending ? "Signing in…" : "Sign in by name"}
        </button>
        {enter.isError ? (
          <div className="notice notice-bad" role="alert">
            {isRefusal(enter.error)
              ? "Name sign-in needs the operator token on this server."
              : friendlyMessage(enter.error)}
          </div>
        ) : null}
      </form>
    </section>
  );
}
