/**
 * The gate card (spec A2 §3): the three ways in with a username.
 * `Sign in` is the card's first form. `Make an account` shows only
 * when the server makes accounts, and `I do not have my password`
 * opens the recovery form.
 *
 * The sign-up form shows the notice that results are public above the
 * control that makes the account (spec R1 §3.1). Publication is a
 * condition of the account, thus the form has no box to tick: the
 * click on `Make an account` is the agreement, and the form says so.
 * A page with a notice version that is not the server's does not make
 * accounts.
 *
 * Each form is a real `<form>` with `autocomplete` tokens, thus a
 * password manager fills and saves it. A password and a recovery code
 * live in component state for the life of the form and go nowhere
 * else on this device.
 */

import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { useApi } from "../api/client";
import { credentialMessage } from "../api/types";
import { PasswordField, RuleList } from "./fields";
import { NOTICE_VERSION } from "./notice";
import { NoticeText, OutOfDate } from "./notice-text";
import {
  allOk,
  isRecoveryCodeShape,
  normalizeUsername,
  passwordChecks,
  usernameChecks,
} from "./rules";

type Mode = "signin" | "signup" | "recover";

const HEADINGS: Record<Mode, string> = {
  signin: "Sign in",
  signup: "Make an account",
  recover: "Get back in with your recovery code",
};

/** The password rule the screen cannot check: the server holds the table. */
const USUAL_NOTE = "Not a password that many people use";

export function GateCard(props: {
  /** True when GET /api/signup said the server makes accounts. */
  signupOpen: boolean;
  /** True when that read answered the constant 404. */
  signupClosed: boolean;
  /** The notice version that read gave, when it answered. */
  noticeVersion: number | undefined;
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
    <section className="card card-hero" aria-labelledby="gate-heading">
      <h2 id="gate-heading" ref={heading} tabIndex={-1}>
        {HEADINGS[mode]}
      </h2>
      {mode === "signin" ? (
        <SignInForm
          username={username}
          onUsername={typeUsername}
          onSignedIn={props.onSignedIn}
        />
      ) : mode === "signup" ? (
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
      <hr className="divider" />
      {mode === "signin" ? (
        <div className="stack-sm">
          <div className="row">
            {props.signupOpen && !signupStale ? (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => go("signup")}
              >
                Make an account
              </button>
            ) : null}
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => go("recover")}
            >
              I do not have my password
            </button>
          </div>
          {props.signupClosed ? (
            <p className="hint">This server isn't making new accounts now.</p>
          ) : null}
          {signupStale ? (
            <OutOfDate>
              This page is out of date, so it can't make an account. Reload it
              and try again.
            </OutOfDate>
          ) : null}
        </div>
      ) : (
        <div>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => go("signin")}
          >
            Back to sign in
          </button>
        </div>
      )}
    </section>
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
      />
      <div>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!ready || signIn.isPending}
        >
          {signIn.isPending ? "Signing in…" : "Sign in"}
        </button>
      </div>
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
  const signUp = useMutation({
    // The form shows the notice above its one control, thus a click on
    // that control is the agreement (spec R1 §3.2).
    mutationFn: () => api.signUp(props.username, password, true),
    onSuccess: (answer) => props.onRecoveryCode(answer.recovery_code),
  });
  const nameChecks = usernameChecks(props.username);
  const wordChecks = passwordChecks(password, props.username);
  const ready = allOk(nameChecks) && allOk(wordChecks);
  return (
    <form
      className="stack"
      onSubmit={(event) => {
        event.preventDefault();
        if (ready && !signUp.isPending) {
          signUp.mutate();
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
        <RuleList id="signup-username-rules" checks={nameChecks} />
        <p className="hint">Capitals you type become small letters.</p>
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
        />
        <p className="hint">
          Any characters work, spaces too. You don't need capitals, digits, or
          symbols. A few unrelated words make a good password.
        </p>
      </div>
      <div className="notice notice-warn" role="note">
        <span>
          <strong>Before you make it:</strong> your username is shown to every
          other player, and it can never be changed. Don't use your real name.
        </span>
      </div>
      <div className="notice notice-warn" role="note" id="signup-notice">
        <div className="stack-sm">
          <NoticeText />
          <p>When you make an account, you agree to this.</p>
        </div>
      </div>
      <div>
        <button
          type="submit"
          className="btn btn-primary"
          aria-describedby="signup-notice"
          disabled={!ready || signUp.isPending}
        >
          {signUp.isPending ? "Making your account…" : "Make an account"}
        </button>
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
    mutationFn: () => api.recover(props.username, code.trim(), password),
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
          recover.mutate();
        }
      }}
    >
      <p className="muted">
        Type the recovery code you saved when you made your account, and choose
        a new password. Each device you were signed in on signs out.
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
        />
      </div>
      <div>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!ready || recover.isPending}
        >
          {recover.isPending ? "Working…" : "Set a new password"}
        </button>
      </div>
      {recover.isError ? <Refusal error={recover.error} /> : null}
      <p className="hint">
        No recovery code? Ask the operator for one. A code from the operator
        starts working 24 hours after it is made.
      </p>
    </form>
  );
}
