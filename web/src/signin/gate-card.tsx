/**
 * The gate card (spec A2 §3): the three ways in with a username.
 * `Sign in` is the card's first form. `Create an account` shows only
 * when the server makes accounts, and `Forgot it?` at the password
 * opens the recovery form. Below the form, two rows open the ways in
 * with no password: a device code and, on a dev server, the open door.
 *
 * The sign-up form shows the notice that results are public above the
 * control that makes the account (spec R1 §3.1). Publication is a
 * condition of the account, thus the form has no box to tick: the
 * click on `Create account` is the agreement, and the form says so.
 * A page with a notice version that is not the server's does not make
 * accounts.
 *
 * The sign-up form also holds the proof-of-work check (spec PW1 §4).
 * It runs while the person types, and `Create account` waits for it.
 *
 * Each form is a real `<form>` with `autocomplete` tokens, thus a
 * password manager fills and saves it. A password and a recovery code
 * live in component state for the life of the form and go nowhere
 * else on this device.
 */

import { Globe, Warning } from "@phosphor-icons/react";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { useApi } from "../api/client";
import { ApiError, credentialMessage } from "../api/types";
import { PasswordField, RuleList } from "./fields";
import { NOTICE_VERSION } from "./notice";
import { NoticeText, OutOfDate } from "./notice-text";
import { DeviceCodeRow, DoorRow } from "./other-ways";
import { ProofField } from "./proof-field";
import {
  allOk,
  isRecoveryCodeShape,
  normalizeUsername,
  PASSWORD_MIN,
  passwordChecks,
  USERNAME_MAX,
  USERNAME_MIN,
  usernameChecks,
} from "./rules";
import { SignupProgress } from "./signup-progress";

type Mode = "signin" | "signup" | "recover";

const HEADINGS: Record<Mode, string> = {
  signin: "Sign in",
  signup: "Create an account",
  recover: "Get back in with your recovery code",
};

/** The helper line of a new username before the player types. */
const USERNAME_SUMMARY = `${USERNAME_MIN} to ${USERNAME_MAX} letters, numbers, or hyphens, starting with a letter`;

/** The helper line of a new password before the player types. */
const PASSWORD_SUMMARY = `At least ${PASSWORD_MIN} characters. A few unrelated words work well.`;

/** The password rule the screen cannot check: the server holds the table. */
const USUAL_NOTE = "Don't use a password that many people use";

/**
 * The usual-password rule when the server refused this typed password
 * for it, and `undefined` in each other condition. The helper line of
 * the field then names the rule until the player changes the password.
 */
function usualRefusal(
  error: unknown,
  refused: string | undefined,
  typed: string,
): string | undefined {
  return error instanceof ApiError &&
    error.refusalCause === "password-usual" &&
    refused === typed
    ? USUAL_NOTE
    : undefined;
}

export function GateCard(props: {
  /** True when GET /api/signup said the server makes accounts. */
  signupOpen: boolean;
  /** True when that read answered the constant 404. */
  signupClosed: boolean;
  /** The notice version that read gave, when it answered. */
  noticeVersion: number | undefined;
  /** True when GET /api/door said the dev door is open (spec A1 §4). */
  doorOpen: boolean;
  /** A session is open on this device and no code waits to be shown. */
  onSignedIn: () => void;
  /** A session is open, and this recovery code shows one time first. */
  onRecoveryCode: (code: string, replaces: boolean) => void;
}): React.JSX.Element {
  const [mode, setMode] = useState<Mode>("signin");
  // The username travels between the forms; a password does not.
  const [username, setUsername] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const moved = useRef(false);

  // A form change moves focus to its heading, thus a screen reader
  // says where the player is. The first render leaves focus alone.
  useEffect(() => {
    void mode;
    if (moved.current) {
      heading.current?.focus();
    }
  }, [mode]);

  const go = (next: Mode) => {
    moved.current = true;
    setMode(next);
  };
  const typeUsername = (typed: string) => setUsername(normalizeUsername(typed));
  // The server's notice is not the text this page holds (spec R1
  // §3.2): a sign-up here would agree to a text the player did not see.
  const signupStale =
    props.signupOpen && props.noticeVersion !== NOTICE_VERSION;

  return (
    <>
      {mode === "signup" ? <SignupProgress current={1} /> : null}
      <section
        className="card card-hero gate-card"
        aria-labelledby="gate-heading"
      >
        <h2 id="gate-heading" ref={heading} tabIndex={-1}>
          {HEADINGS[mode]}
        </h2>
        {mode === "signin" ? (
          <>
            <SignInForm
              username={username}
              onUsername={typeUsername}
              onSignedIn={props.onSignedIn}
              onForgot={() => go("recover")}
            />
            {props.signupOpen && !signupStale ? (
              <button
                type="button"
                className="btn btn-secondary btn-block"
                onClick={() => go("signup")}
              >
                Create an account
              </button>
            ) : null}
            {props.signupClosed ? (
              <p className="hint">This server isn't making new accounts now.</p>
            ) : null}
            {signupStale ? (
              <OutOfDate>
                This page is out of date, so it can't make an account. Reload it
                and try again.
              </OutOfDate>
            ) : null}
            <div className="row-list gate-more">
              <DeviceCodeRow onSignedIn={props.onSignedIn} />
              {props.doorOpen ? <DoorRow /> : null}
            </div>
          </>
        ) : (
          <>
            {mode === "signup" ? (
              <SignUpForm
                username={username}
                onUsername={typeUsername}
                onRecoveryCode={(code) => props.onRecoveryCode(code, false)}
              />
            ) : (
              <RecoverForm
                username={username}
                onUsername={typeUsername}
                onRecoveryCode={(code) => props.onRecoveryCode(code, true)}
              />
            )}
            <div className="gate-back">
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => go("signin")}
              >
                Back to sign in
              </button>
            </div>
          </>
        )}
      </section>
    </>
  );
}

function UsernameField(props: {
  id: string;
  value: string;
  onChange: (typed: string) => void;
  describedBy?: string;
}): React.JSX.Element {
  return (
    <div className="field">
      <label className="label" htmlFor={props.id}>
        Username
      </label>
      <input
        id={props.id}
        className="input"
        name="username"
        autoComplete="username"
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
        aria-describedby={props.describedBy}
        value={props.value}
        onChange={(event) => props.onChange(event.target.value)}
      />
    </div>
  );
}

function Refusal(props: { error: unknown }): React.JSX.Element {
  return (
    <div className="notice notice-bad" role="alert">
      {credentialMessage(props.error)}
    </div>
  );
}

function SignInForm(props: {
  username: string;
  onUsername: (typed: string) => void;
  onSignedIn: () => void;
  /** The player has no password to type: open the recovery form. */
  onForgot: () => void;
}): React.JSX.Element {
  const api = useApi();
  const [password, setPassword] = useState("");
  const signIn = useMutation({
    mutationFn: () => api.signIn(props.username, password),
    // The cookie came with the answer; the shell reads me again.
    onSuccess: props.onSignedIn,
  });
  const ready = props.username !== "" && password !== "";
  return (
    <form
      className="stack"
      onSubmit={(event) => {
        event.preventDefault();
        if (ready && !signIn.isPending) {
          signIn.mutate();
        }
      }}
    >
      <UsernameField
        id="signin-username"
        value={props.username}
        onChange={props.onUsername}
      />
      <PasswordField
        id="signin-password"
        label="Password"
        autoComplete="current-password"
        value={password}
        onChange={setPassword}
        labelAction={
          <button
            type="button"
            className="text-button"
            onClick={props.onForgot}
          >
            Forgot it?
          </button>
        }
      />
      <button
        type="submit"
        className="btn btn-primary btn-block"
        disabled={!ready || signIn.isPending}
      >
        {signIn.isPending ? "Signing in…" : "Sign in"}
      </button>
      {signIn.isError ? <Refusal error={signIn.error} /> : null}
    </form>
  );
}

function SignUpForm(props: {
  username: string;
  onUsername: (typed: string) => void;
  onRecoveryCode: (code: string) => void;
}): React.JSX.Element {
  const api = useApi();
  const [password, setPassword] = useState("");
  // The payload of the solved challenge (spec PW1 §3.2), and a count
  // that gives the check a new widget when the server refuses one.
  const [proof, setProof] = useState<string | undefined>(undefined);
  const [proofRound, setProofRound] = useState(0);
  const signUp = useMutation({
    // The form shows the notice above its one control, thus a click on
    // that control is the agreement (spec R1 §3.2).
    mutationFn: (word: string) => api.signUp(props.username, word, true, proof),
    onSuccess: (answer) => props.onRecoveryCode(answer.recovery_code),
    onError: (error) => {
      // The server refused the payload: it ran out, or it is spent.
      // A new widget reads a new challenge and starts again.
      if (error instanceof ApiError && error.refusalCause === "proof") {
        setProof(undefined);
        setProofRound((round) => round + 1);
      }
    },
  });
  const nameChecks = usernameChecks(props.username);
  const wordChecks = passwordChecks(password, props.username);
  const ready = allOk(nameChecks) && allOk(wordChecks) && proof !== undefined;
  return (
    <form
      className="stack"
      onSubmit={(event) => {
        event.preventDefault();
        if (ready && !signUp.isPending) {
          signUp.mutate(password);
        }
      }}
    >
      <div className="stack-sm">
        <UsernameField
          id="signup-username"
          value={props.username}
          onChange={props.onUsername}
          describedBy="signup-username-rules"
        />
        <RuleList
          id="signup-username-rules"
          checks={nameChecks}
          summary={USERNAME_SUMMARY}
          typed={props.username !== ""}
        />
        <p className="hint">Capital letters become lowercase.</p>
      </div>
      <div className="notice notice-warn" role="note">
        <Warning size={18} aria-hidden="true" />
        <span>
          Everyone sees this name and it can never be changed. Don't use your
          real name.
        </span>
      </div>
      <div className="stack-sm">
        <PasswordField
          id="signup-password"
          label="Password"
          autoComplete="new-password"
          describedBy="signup-password-rules"
          value={password}
          onChange={setPassword}
        />
        <RuleList
          id="signup-password-rules"
          checks={wordChecks}
          notes={[USUAL_NOTE]}
          summary={PASSWORD_SUMMARY}
          typed={password !== ""}
          refused={usualRefusal(signUp.error, signUp.variables, password)}
        />
      </div>
      <div className="notice notice-warn" role="note" id="signup-notice">
        <Globe size={18} aria-hidden="true" />
        <NoticeText />
      </div>
      <ProofField key={proofRound} onProof={setProof} />
      <div className="stack-sm">
        <button
          type="submit"
          className="btn btn-primary btn-block"
          aria-describedby="signup-notice signup-agreement"
          disabled={!ready || signUp.isPending}
        >
          {signUp.isPending ? "Creating your account…" : "Create account"}
        </button>
        <p className="hint gate-agreement" id="signup-agreement">
          By creating an account, you agree to this.
        </p>
      </div>
      {signUp.isError ? <Refusal error={signUp.error} /> : null}
    </form>
  );
}

function RecoverForm(props: {
  username: string;
  onUsername: (typed: string) => void;
  onRecoveryCode: (code: string) => void;
}): React.JSX.Element {
  const api = useApi();
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const recover = useMutation({
    mutationFn: (word: string) =>
      api.recover(props.username, code.trim(), word),
    onSuccess: (answer) => props.onRecoveryCode(answer.recovery_code),
  });
  const wordChecks = passwordChecks(password, props.username);
  const ready =
    props.username !== "" && isRecoveryCodeShape(code) && allOk(wordChecks);
  return (
    <form
      className="stack"
      onSubmit={(event) => {
        event.preventDefault();
        if (ready && !recover.isPending) {
          recover.mutate(password);
        }
      }}
    >
      <p className="muted">
        Enter the recovery code you saved when you created your account, and
        choose a new password. Every device you were signed in on signs out.
      </p>
      <UsernameField
        id="recover-username"
        value={props.username}
        onChange={props.onUsername}
      />
      <div className="field">
        <label className="label" htmlFor="recover-code">
          Recovery code
        </label>
        <input
          id="recover-code"
          className="input recovery-input"
          autoComplete="off"
          autoCapitalize="characters"
          autoCorrect="off"
          spellCheck={false}
          aria-describedby="recover-code-hint"
          placeholder="ABCD-EFGH-JKMN-PQRS-TUVW-XYZ2"
          value={code}
          onChange={(event) => setCode(event.target.value)}
        />
        <p className="hint" id="recover-code-hint">
          24 letters and digits. Capitals, spaces, and hyphens don't matter.
        </p>
      </div>
      <div className="stack-sm">
        <PasswordField
          id="recover-password"
          label="New password"
          autoComplete="new-password"
          describedBy="recover-password-rules"
          value={password}
          onChange={setPassword}
        />
        <RuleList
          id="recover-password-rules"
          checks={wordChecks}
          notes={[USUAL_NOTE]}
          summary={PASSWORD_SUMMARY}
          typed={password !== ""}
          refused={usualRefusal(recover.error, recover.variables, password)}
        />
      </div>
      <button
        type="submit"
        className="btn btn-primary btn-block"
        disabled={!ready || recover.isPending}
      >
        {recover.isPending ? "Working…" : "Set a new password"}
      </button>
      {recover.isError ? <Refusal error={recover.error} /> : null}
      <p className="hint">
        No recovery code? Ask the operator for one. A code from the operator
        starts working 24 hours after it is made.
      </p>
    </form>
  );
}
