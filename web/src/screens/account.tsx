/**
 * The account screen (spec A1 §3, grown by spec BR1 §4–5 and spec A2
 * §3.4): the picture and the description, the password and the
 * recovery code, the signed-in devices with "Add a device" and
 * sign-out, the data download, and `Public data` (spec R1 §3.1): the
 * facts of the public database that the short notice does not say.
 * The writers write for the resolved caller alone — no player
 * parameter on this screen.
 *
 * The username is the one name of a player (spec A2 ruling 3) and it
 * does not change, thus this screen shows it and edits no name.
 *
 * A server with no accounts (spec M1 ruling 7) lists no session: the
 * password, device, and sign-out sections then say so or stay away
 * instead of offering moves that do nothing.
 */

import { DeviceMobile, Laptop } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { useApi } from "../api/client";
import type { DeviceCodeView, MeView, SessionRow } from "../api/types";
import { credentialMessage, friendlyMessage } from "../api/types";
import { PasswordField, RuleList } from "../signin/fields";
import { RecoveryCodeStep } from "../signin/recovery-code-step";
import { allOk, passwordChecks } from "../signin/rules";
import { AvatarCircle } from "../ui/avatar";
import { useNow } from "../ui/countdown";
import { downscaleImage } from "../ui/downscale";
import { formatInstantDay, formatRemaining } from "../ui/format";
import { StreakName } from "../ui/streak-name";

/** The D1 cap, mirrored for the counter — the server owns the rule. */
const DESCRIPTION_LIMIT = 500;

export function AccountScreen(): React.JSX.Element {
  const api = useApi();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.getMe() });
  if (me.isPending) {
    return (
      <p className="subtle" aria-busy="true">
        Loading…
      </p>
    );
  }
  if (me.isError || me.data === undefined) {
    return (
      <div className="notice notice-bad" role="alert">
        {friendlyMessage(me.error)}
      </div>
    );
  }
  return <AccountBody me={me.data} />;
}

function AccountBody(props: { me: MeView }): React.JSX.Element {
  const api = useApi();
  const { me } = props;
  const sessions = useQuery({
    queryKey: ["sessions"],
    queryFn: () => api.getSessions(),
  });
  const accounts =
    sessions.data === undefined ? null : sessions.data.sessions.length > 0;
  return (
    <div className="page-narrow stack-lg" style={{ margin: "0 auto" }}>
      <div className="page-header" style={{ marginBottom: 0 }}>
        <h1>Your account</h1>
      </div>
      <ProfileCard me={me} />
      <DescriptionCard me={me} />
      {accounts === false ? null : <PasswordCard me={me} />}
      {accounts === false || !me.has_password ? null : (
        <RecoveryCodeCard me={me} />
      )}
      {accounts === false ? (
        <section className="card card-quiet">
          <h2>Devices</h2>
          <p className="muted">
            This server runs without sign-in, so there are no devices to manage.
          </p>
        </section>
      ) : (
        <DevicesCard
          rows={sessions.data?.sessions}
          error={sessions.isError ? sessions.error : null}
        />
      )}
      <section className="card" aria-labelledby="data-heading">
        <h2 id="data-heading">Your data</h2>
        <p className="muted small">
          Download each sketch and set of words you've sent, with your results
          for each day that's been revealed, as one file.
        </p>
        <div>
          <a className="btn btn-secondary" href={api.exportUrl()} download>
            Download my data
          </a>
        </div>
      </section>
      <PublicDataCard />
      {accounts === true ? <SignOutCard me={me} /> : null}
    </div>
  );
}

/**
 * `Public data` (spec R1 §3.1): what the public database holds, who
 * can read it, how long a snapshot stays, and where the snapshots are.
 */
function PublicDataCard(): React.JSX.Element {
  const api = useApi();
  // The key each reader of the season facts uses: one request.
  const about = useQuery({
    queryKey: ["about"],
    queryFn: () => api.getAbout(),
    staleTime: Number.POSITIVE_INFINITY,
  });
  const address = about.data?.public_data_url;
  return (
    <section className="card" aria-labelledby="public-data-heading">
      <h2 id="public-data-heading">Public data</h2>
      <p className="muted small">
        Your results are published in an open database after each day closes.
      </p>
      <ul className="fact-list">
        <li>
          The database holds your username, each score, the words you typed, and
          each sketch.
        </li>
        <li>Anyone can download it and study it.</li>
        <li>
          A published snapshot stays published, with your username in it, also
          after your account is gone.
        </li>
      </ul>
      {about.isError ? (
        <div className="notice notice-bad" role="alert">
          {friendlyMessage(about.error)}
        </div>
      ) : address === undefined ? null : address === null ? (
        <p className="muted small">No snapshot is published yet.</p>
      ) : (
        <div>
          <a
            className="btn btn-secondary"
            href={address}
            target="_blank"
            rel="noreferrer noopener"
          >
            Get the public database
          </a>
        </div>
      )}
    </section>
  );
}

function ProfileCard(props: { me: MeView }): React.JSX.Element {
  const api = useApi();
  const queryClient = useQueryClient();
  const { me } = props;
  const fileRef = useRef<HTMLInputElement>(null);
  const invalidateMe = () =>
    queryClient.invalidateQueries({ queryKey: ["me"] });
  const putAvatar = useMutation({
    mutationFn: async (file: File) => {
      const image = await downscaleImage(file);
      return api.putAvatar(image);
    },
    onSuccess: () => void invalidateMe(),
  });
  const removeAvatar = useMutation({
    mutationFn: () => api.deleteAvatar(),
    onSuccess: () => void invalidateMe(),
  });
  const busy = putAvatar.isPending || removeAvatar.isPending;
  const avatarError = putAvatar.error ?? removeAvatar.error;

  return (
    <section className="card card-hero" aria-label="Profile">
      <div className="row" style={{ gap: 20 }}>
        <AvatarCircle
          player={me.player}
          avatarHash={me.avatar_hash}
          size={88}
          streak={me.streak}
        />
        <div className="stack-sm">
          <h2 style={{ fontSize: 24 }}>
            <StreakName streak={me.streak}>{me.player}</StreakName>
          </h2>
          <span className="subtle small">
            Your username. Other players see it on the boards, and it can't be
            changed.
          </span>
          {me.streak > 0 ? (
            <span
              className="badge badge-accent"
              style={{ alignSelf: "flex-start" }}
            >
              {me.streak}-day streak
            </span>
          ) : null}
        </div>
      </div>
      <div className="row">
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          aria-label="Choose a profile picture"
          style={{ display: "none" }}
          onChange={(event) => {
            const file = event.target.files?.[0];
            // The same file picked twice must fire again.
            event.target.value = "";
            if (file !== undefined) {
              putAvatar.mutate(file);
            }
          }}
        />
        <button
          type="button"
          className="btn btn-secondary"
          disabled={busy}
          onClick={() => fileRef.current?.click()}
        >
          {putAvatar.isPending ? "Uploading…" : "Change picture"}
        </button>
        {me.avatar_hash === null ? null : (
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy}
            onClick={() => removeAvatar.mutate()}
          >
            Remove picture
          </button>
        )}
      </div>
      {avatarError === null ? null : (
        <div className="notice notice-bad" role="alert">
          {friendlyMessage(avatarError)}
        </div>
      )}
    </section>
  );
}

function DescriptionCard(props: { me: MeView }): React.JSX.Element {
  const api = useApi();
  const queryClient = useQueryClient();
  const { me } = props;
  const [draft, setDraft] = useState(me.description);
  const [savedNote, setSavedNote] = useState(false);
  // Resync the draft when the stored description moves under it —
  // the server canonicalizes (trim), and a save from a second tab
  // must not be silently overwritten by a stale draft here. The
  // render-time adjustment keeps the other state (the saved note)
  // alive, which a remount key would not.
  const [baseline, setBaseline] = useState(me.description);
  if (me.description !== baseline) {
    setBaseline(me.description);
    setDraft(me.description);
  }
  const saveDescription = useMutation({
    mutationFn: (text: string) => api.putAccount(text),
    onSuccess: () => {
      setSavedNote(true);
      void queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });

  return (
    <section className="card" aria-labelledby="about-heading">
      <h2 id="about-heading">About you</h2>
      <textarea
        className="input"
        aria-label="About you"
        placeholder="A few lines about yourself, if you like."
        value={draft}
        maxLength={DESCRIPTION_LIMIT}
        onChange={(event) => {
          setDraft(event.target.value);
          setSavedNote(false);
        }}
      />
      <div className="row">
        <button
          type="button"
          className="btn btn-primary"
          disabled={
            saveDescription.isPending || draft.trim() === me.description
          }
          onClick={() => saveDescription.mutate(draft.trim())}
        >
          {saveDescription.isPending ? "Saving…" : "Save"}
        </button>
        <span className="subtle small" aria-live="polite">
          {savedNote ? "Saved" : `${draft.length} of ${DESCRIPTION_LIMIT}`}
        </span>
      </div>
      {saveDescription.isError ? (
        <div className="notice notice-bad" role="alert">
          {friendlyMessage(saveDescription.error)}
        </div>
      ) : null}
    </section>
  );
}

/** The password rule the screen cannot check: the server holds the table. */
const USUAL_NOTE = "Not a password that many people use";

/**
 * A username field that a password manager reads and a person does
 * not: it ties the password fields of a form to the account. It is
 * out of the tab sequence and out of the accessibility tree.
 */
function ManagerUsername(props: { player: string }): React.JSX.Element {
  return (
    <input
      className="visually-hidden"
      type="text"
      name="username"
      autoComplete="username"
      value={props.player}
      readOnly
      tabIndex={-1}
      aria-hidden="true"
    />
  );
}

/**
 * `Change password`, or `Set a password` for a player from before
 * spec A2 (§3.4, §8). The first password asks for no current one —
 * the session is sufficient — and its answer holds the first recovery
 * code, which shows one time here.
 */
function PasswordCard(props: { me: MeView }): React.JSX.Element {
  const api = useApi();
  const queryClient = useQueryClient();
  const { me } = props;
  const first = !me.has_password;
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  // The first recovery code, until the player says they have it. It
  // outlives the me read that turns this card into "Change password".
  const [code, setCode] = useState<string | null>(null);
  // What the last change did, in words. Written when the answer
  // lands: `first` moves with the me read that follows.
  const [done, setDone] = useState<string | null>(null);
  const change = useMutation({
    mutationFn: () => api.setPassword(next, first ? undefined : current),
    onSuccess: (answer) => {
      setCurrent("");
      setNext("");
      setCode(answer.recovery_code);
      setDone(
        `Your password is ${first ? "set" : "changed"}.${
          answer.signed_out === 0
            ? ""
            : answer.signed_out === 1
              ? " 1 other device was signed out."
              : ` ${answer.signed_out} other devices were signed out.`
        }`,
      );
      // has_password moved, and each other device signed out.
      void queryClient.invalidateQueries({ queryKey: ["me"] });
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
  const checks = passwordChecks(next, me.player);
  const ready = allOk(checks) && (first || current !== "");
  const title = first ? "Set a password" : "Change password";

  if (code !== null) {
    return (
      <section className="card" aria-label="Your recovery code">
        <RecoveryCodeStep code={code} onDone={() => setCode(null)} />
      </section>
    );
  }
  return (
    <section className="card" aria-labelledby="password-heading">
      <h2 id="password-heading">{title}</h2>
      <p className="muted small">
        {first
          ? `This account has no password yet. Set one, and you can sign in on a new device with your username (${me.player}) and the password.`
          : "Each other device signs out when you change your password."}
      </p>
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          if (ready && !change.isPending) {
            setDone(null);
            change.mutate();
          }
        }}
      >
        <ManagerUsername player={me.player} />
        {first ? null : (
          <PasswordField
            id="account-current-password"
            label="Current password"
            autoComplete="current-password"
            value={current}
            onChange={setCurrent}
          />
        )}
        <div className="stack-sm">
          <PasswordField
            id="account-new-password"
            label="New password"
            autoComplete="new-password"
            describedBy="account-password-rules"
            value={next}
            onChange={setNext}
          />
          <RuleList
            id="account-password-rules"
            checks={checks}
            notes={[USUAL_NOTE]}
          />
        </div>
        <div>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={!ready || change.isPending}
          >
            {change.isPending ? "Saving…" : title}
          </button>
        </div>
        {change.isError ? (
          <div className="notice notice-bad" role="alert">
            {credentialMessage(change.error)}
          </div>
        ) : done === null ? null : (
          <div className="notice notice-good" role="status">
            {done}
          </div>
        )}
      </form>
    </section>
  );
}

/**
 * `New recovery code` (spec A2 §3.4): the player types the current
 * password, the earlier code is dead, and the new one shows one time.
 */
function RecoveryCodeCard(props: { me: MeView }): React.JSX.Element {
  const api = useApi();
  const [current, setCurrent] = useState("");
  const [code, setCode] = useState<string | null>(null);
  const make = useMutation({
    mutationFn: () => api.newRecoveryCode(current),
    onSuccess: (answer) => {
      setCurrent("");
      setCode(answer.recovery_code);
    },
  });

  if (code !== null) {
    return (
      <section className="card" aria-label="Your new recovery code">
        <RecoveryCodeStep code={code} replaces onDone={() => setCode(null)} />
      </section>
    );
  }
  return (
    <section className="card" aria-labelledby="recovery-heading">
      <h2 id="recovery-heading">Recovery code</h2>
      <p className="muted small">
        Your recovery code gets you back in if you lose your password. It was
        shown one time, when it was made. If you don't have it, make a new one:
        the earlier code stops working.
      </p>
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          if (current !== "" && !make.isPending) {
            make.mutate();
          }
        }}
      >
        <ManagerUsername player={props.me.player} />
        <PasswordField
          id="recovery-current-password"
          label="Current password, to make a new code"
          autoComplete="current-password"
          value={current}
          onChange={setCurrent}
        />
        <div>
          <button
            type="submit"
            className="btn btn-secondary"
            disabled={current === "" || make.isPending}
          >
            {make.isPending ? "Working…" : "New recovery code"}
          </button>
        </div>
        {make.isError ? (
          <div className="notice notice-bad" role="alert">
            {credentialMessage(make.error)}
          </div>
        ) : null}
      </form>
    </section>
  );
}

function isPhone(label: string): boolean {
  return /iPhone|Android|iPad/.test(label);
}

function DevicesCard(props: {
  rows: ReadonlyArray<SessionRow> | undefined;
  error: unknown;
}): React.JSX.Element {
  const api = useApi();
  const queryClient = useQueryClient();
  const [code, setCode] = useState<DeviceCodeView | null>(null);
  // The devices signed in when the code was shown: a new id in the
  // list after that is the device the code signed in.
  const [known, setKnown] = useState<ReadonlySet<string>>(() => new Set());
  const [added, setAdded] = useState<string | null>(null);
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["sessions"] });
  // While a code is on screen, watch for the new device to appear.
  useQuery({
    queryKey: ["sessions"],
    queryFn: () => api.getSessions(),
    refetchInterval: code === null ? false : 4000,
  });
  const issue = useMutation({
    mutationFn: () => api.issueDeviceCode(),
    onSuccess: (answer) => {
      setKnown(new Set((props.rows ?? []).map((row) => row.id)));
      setAdded(null);
      setCode(answer);
    },
  });
  const arrived =
    code === null
      ? undefined
      : (props.rows ?? []).find((row) => !known.has(row.id) && !row.current);
  if (arrived !== undefined) {
    // Render-time adjustment: the code did its one job.
    setCode(null);
    setAdded(arrived.label);
  }
  const remove = useMutation({
    mutationFn: (id: string) => api.removeSession(id),
    onSettled: () => void refresh(),
  });
  const others = useMutation({
    mutationFn: () => api.signOutOthers(),
    onSettled: () => void refresh(),
  });
  const rows = props.rows ?? [];
  const otherCount = rows.filter((row) => !row.current).length;

  return (
    <section className="card" aria-labelledby="devices-heading">
      <div className="row-between">
        <h2 id="devices-heading">Devices</h2>
        <button
          type="button"
          className="btn btn-primary"
          disabled={issue.isPending || props.rows === undefined}
          onClick={() => issue.mutate()}
        >
          {code === null ? "Add a device" : "Get a new code"}
        </button>
      </div>
      {code === null ? null : (
        <DeviceCodePanel code={code} onDone={() => setCode(null)} />
      )}
      {added === null ? null : (
        <div className="notice notice-good" role="status">
          {added} is signed in.
        </div>
      )}
      {issue.isError ? (
        <div className="notice notice-bad" role="alert">
          {friendlyMessage(issue.error)}
        </div>
      ) : null}
      {props.error !== null ? (
        <div className="notice notice-bad" role="alert">
          {friendlyMessage(props.error)}
        </div>
      ) : (
        <ul
          className="stack-sm"
          style={{ margin: 0, padding: 0, listStyle: "none" }}
        >
          {rows.map((row) => {
            const Icon = isPhone(row.label) ? DeviceMobile : Laptop;
            return (
              <li
                key={row.id}
                className="row-between"
                style={{ padding: "6px 0" }}
              >
                <span className="row" style={{ gap: 12, flexWrap: "nowrap" }}>
                  <Icon size={24} aria-hidden="true" className="subtle" />
                  <span className="stack-sm" style={{ gap: 0 }}>
                    <span style={{ fontWeight: 600 }}>
                      {row.label}
                      {row.current ? (
                        <span
                          className="badge badge-good"
                          style={{ marginLeft: 8 }}
                        >
                          This device
                        </span>
                      ) : null}
                    </span>
                    <span className="subtle small">
                      Signed in {formatInstantDay(row.created_at)}
                    </span>
                  </span>
                </span>
                {row.current ? null : (
                  <button
                    type="button"
                    className="btn btn-ghost"
                    disabled={remove.isPending}
                    onClick={() => remove.mutate(row.id)}
                  >
                    Sign out
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {otherCount > 0 ? (
        <div>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={others.isPending}
            onClick={() => others.mutate()}
          >
            Sign out of all other devices
          </button>
        </div>
      ) : null}
    </section>
  );
}

function DeviceCodePanel(props: {
  code: DeviceCodeView;
  onDone: () => void;
}): React.JSX.Element {
  const now = useNow(1000);
  const remaining = Date.parse(props.code.expires_at) - now;
  const expired = Number.isNaN(remaining) || remaining <= 0;
  return (
    <div
      className="stack"
      style={{
        padding: 16,
        borderRadius: 12,
        background: "var(--accent-soft)",
      }}
      aria-live="polite"
    >
      {expired ? (
        <p>This code has expired. Get a new one to add a device.</p>
      ) : (
        <>
          <p>
            On your other device, open Starvector and find “Signed in on another
            device?”. Then type this code:
          </p>
          <div
            style={{
              fontFamily: "var(--mono)",
              fontSize: 34,
              fontWeight: 700,
              letterSpacing: "0.12em",
            }}
          >
            {props.code.code}
          </div>
          <p className="muted small">
            It works once and expires in {formatRemaining(remaining)}.
          </p>
        </>
      )}
      <div>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={props.onDone}
        >
          Done
        </button>
      </div>
    </div>
  );
}

function SignOutCard(props: { me: MeView }): React.JSX.Element {
  const api = useApi();
  const queryClient = useQueryClient();
  const signOut = useMutation({
    mutationFn: () => api.signOut(),
    onSuccess: () => {
      // Each active query reads again: me answers 401 and the shell
      // shows the landing page. The cached screens go with the session.
      void queryClient.resetQueries();
    },
  });
  return (
    <section className="card card-quiet" aria-labelledby="signout-heading">
      <h2 id="signout-heading">Sign out</h2>
      <p className="muted small">
        Sign out of this device. To sign back in, type your username and
        password, or use a code from another device.
      </p>
      {props.me.has_password ? null : (
        <div className="notice notice-warn" role="note">
          This account has no password yet. Set one before you sign out, or the
          only ways back in are a code from another signed-in device and a
          recovery code from the operator.
        </div>
      )}
      <div>
        <button
          type="button"
          className="btn btn-danger"
          disabled={signOut.isPending}
          onClick={() => signOut.mutate()}
        >
          Sign out of this device
        </button>
      </div>
      {signOut.isError ? (
        <div className="notice notice-bad" role="alert">
          {friendlyMessage(signOut.error)}
        </div>
      ) : null}
    </section>
  );
}
