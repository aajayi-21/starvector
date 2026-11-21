/**
 * The account screen (spec A1 §3, grown by spec BR1 §4–5 and spec A2
 * §3.4): the picture and the description, the password and the
 * recovery code, the signed-in devices with "Add a device" and
 * sign-out, the data download, and `Public data` (spec R1 §3.1): the
 * facts of the public database that the short notice does not say.
 * The writers write for the resolved caller alone — no player
 * parameter on this screen.
 *
 * The page is a list of rows on hairlines, at the full width: the name
 * of a section on the left and its controls on the right. On a phone
 * the two parts stack. No row has a box; the fields and the buttons
 * are the only things with an edge (styles/account.css).
 *
 * The last row holds the data download, the sign-out of this device,
 * and `Delete account` as quiet red words. Those words open the
 * `Delete my account` section (spec MD1 §4.3), the last thing on the
 * page: what goes and what stays, the username typed again and the
 * password, then a red button.
 *
 * The username is the one name of a player (spec A2 ruling 3) and it
 * does not change, thus this screen shows it and edits no name.
 *
 * A server with no accounts (spec M1 ruling 7) lists no session: the
 * password, device, and sign-out sections then say so or stay away
 * instead of offering moves that do nothing.
 */

import {
  DownloadSimple,
  Eye,
  LockSimple,
  Warning,
  X,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

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
import { streakLabel } from "../ui/streak";
import { StreakName } from "../ui/streak-name";

/** The D1 cap, mirrored for the counter — the server owns the rule. */
const DESCRIPTION_LIMIT = 500;

/**
 * One row of the page: the name of the section and a short note on the
 * left, and the controls on the right. The heading names the section
 * for assistive technology.
 */
function AccountRow(props: {
  headingId: string;
  title: string;
  note?: React.ReactNode;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <section className="account-row" aria-labelledby={props.headingId}>
      <div className="account-row-title">
        <h2 id={props.headingId}>{props.title}</h2>
        {props.note === undefined ? null : (
          <p className="muted small">{props.note}</p>
        )}
      </div>
      <div className="account-row-body">{props.children}</div>
    </section>
  );
}

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
    <div className="account">
      {/* The username is the visible title of the page. This heading
          names the page for a screen reader. */}
      <h1 className="visually-hidden">Your account</h1>
      <ProfileCard me={me} />
      <DescriptionCard me={me} />
      {accounts === false ? null : <PasswordCard me={me} />}
      {accounts === false || !me.has_password ? null : (
        <RecoveryCodeCard me={me} />
      )}
      {accounts === false ? (
        <AccountRow headingId="devices-heading" title="Devices">
          <p className="muted">
            This server runs without sign-in, so there are no devices to manage.
          </p>
        </AccountRow>
      ) : (
        <DevicesCard
          rows={sessions.data?.sessions}
          error={sessions.isError ? sessions.error : null}
        />
      )}
      <PublicDataCard />
      <ClosingCard me={me} accounts={accounts === true} />
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
    <AccountRow
      headingId="public-data-heading"
      title="Public data"
      note="Your results are published in an open database after each day closes."
    >
      <ul className="fact-list account-facts">
        {/* Spec SS1 §10: the fact of notice version 2. */}
        <li>
          After you send, every player who has sent that day can see your
          sketch. They see the sketch alone, not your words.
        </li>
        <li>
          The database holds your username, every score, the words you typed,
          and every sketch.
        </li>
        <li>Anyone can download it and study it.</li>
        <li>
          A published snapshot stays published, with your username in it, even
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
    </AccountRow>
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
    <section className="account-head" aria-label="Profile">
      <AvatarCircle
        player={me.player}
        avatarHash={me.avatar_hash}
        size={88}
        streak={me.streak}
      />
      <div className="account-head-text">
        <h2 className="h-display">
          <StreakName streak={me.streak}>{me.player}</StreakName>
        </h2>
        {/* The top bar holds the streak on a wide screen and hides it
            on a phone, thus the phone shows it here. */}
        {me.streak > 0 ? (
          <span className="badge badge-accent account-streak">
            {streakLabel(me.streak)}
          </span>
        ) : null}
        <p className="muted">
          Your username. Other players see it on the leaderboard, and it can't
          be changed.
        </p>
      </div>
      <div className="account-head-controls">
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
        <div className="notice notice-bad account-head-error" role="alert">
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
    <AccountRow
      headingId="about-heading"
      title="About you"
      note={`Up to ${DESCRIPTION_LIMIT} characters.`}
    >
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
          className="btn btn-secondary"
          disabled={
            saveDescription.isPending || draft.trim() === me.description
          }
          onClick={() => saveDescription.mutate(draft.trim())}
        >
          {saveDescription.isPending ? "Saving…" : "Save"}
        </button>
        <span className="subtle small tabular" aria-live="polite">
          {savedNote ? "Saved" : `${draft.length} of ${DESCRIPTION_LIMIT}`}
        </span>
      </div>
      {saveDescription.isError ? (
        <div className="notice notice-bad" role="alert">
          {friendlyMessage(saveDescription.error)}
        </div>
      ) : null}
    </AccountRow>
  );
}

/** The password rule the screen cannot check: the server holds the table. */
const USUAL_NOTE = "Don't use a password that many people use";

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
 * `Password`: the button says `Change password`, or `Set a password`
 * for a player from before spec A2 (§3.4, §8). The first password asks
 * for no current one — the session is sufficient — and its answer
 * holds the first recovery code, which shows one time here.
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
      <section className="account-row" aria-label="Your recovery code">
        <div className="account-row-title">
          <h2>Password</h2>
        </div>
        <div className="account-row-body">
          <RecoveryCodeStep code={code} onDone={() => setCode(null)} />
        </div>
      </section>
    );
  }
  return (
    <AccountRow
      headingId="password-heading"
      title="Password"
      note={
        first
          ? `This account has no password yet. Set one, and you can sign in on a new device with your username (${me.player}) and password.`
          : "Changing your password signs out your other devices."
      }
    >
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
            summary="At least 12 characters. A few unrelated words work well."
            typed={next !== ""}
          />
        </div>
        <div>
          <button
            type="submit"
            className="btn btn-secondary"
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
    </AccountRow>
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
      <section className="account-row" aria-label="Your new recovery code">
        <div className="account-row-title">
          <h2>Recovery code</h2>
        </div>
        <div className="account-row-body">
          <RecoveryCodeStep code={code} replaces onDone={() => setCode(null)} />
        </div>
      </section>
    );
  }
  return (
    <AccountRow
      headingId="recovery-heading"
      title="Recovery code"
      note="Your recovery code gets you back in if you lose your password. It was shown once, when it was created. If you've lost it, make a new one; the old code stops working."
    >
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
    </AccountRow>
  );
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
    <AccountRow
      headingId="devices-heading"
      title="Devices"
      note="Where you're signed in."
    >
      {props.error !== null ? (
        <div className="notice notice-bad" role="alert">
          {friendlyMessage(props.error)}
        </div>
      ) : (
        <ul className="account-devices">
          {rows.map((row) => (
            <li key={row.id}>
              <span className="account-device">
                <span className="account-device-name">{row.label}</span>
                <span className="muted small">
                  Signed in {formatInstantDay(row.created_at)}
                </span>
              </span>
              {row.current ? (
                <span className="muted small">This device</span>
              ) : (
                <button
                  type="button"
                  className="btn btn-secondary account-device-out"
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(row.id)}
                >
                  Sign out
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="account-buttons">
        <button
          type="button"
          className="btn btn-secondary"
          disabled={issue.isPending || props.rows === undefined}
          onClick={() => issue.mutate()}
        >
          {code === null ? "Add a device" : "Get a new code"}
        </button>
        {otherCount > 0 ? (
          <button
            type="button"
            className="btn btn-secondary"
            disabled={others.isPending}
            onClick={() => others.mutate()}
          >
            Sign out of all other devices
          </button>
        ) : null}
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
    </AccountRow>
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
    <div className="account-code" aria-live="polite">
      {expired ? (
        <p>This code has expired. Get a new one to add a device.</p>
      ) : (
        <>
          <p>
            On your other device, open Starvector, find “Signed in on another
            device?”, and enter this code:
          </p>
          <div className="code account-code-value">{props.code.code}</div>
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

/**
 * The last row of the page: one line for each closing move, a sentence
 * that says what the move does and then its button. The data download
 * is there on each server. The sign-out of this device and
 * `Delete account` are there when the server has accounts.
 *
 * `Delete account` is quiet red words, not a button with an edge. It
 * opens the `Delete my account` section below the row and closes it
 * again. The section is closed at first, thus the one move that cannot
 * be put back is two deliberate clicks away.
 */
function ClosingCard(props: {
  me: MeView;
  accounts: boolean;
}): React.JSX.Element {
  const api = useApi();
  const queryClient = useQueryClient();
  const { me, accounts } = props;
  const [deleteOpen, setDeleteOpen] = useState(false);
  // The anonymous name of the deleted account, when the deletion is done.
  const [identifier, setIdentifier] = useState<string | null>(null);
  const deleteRow = useRef<HTMLButtonElement>(null);
  const signOut = useMutation({
    mutationFn: () => api.signOut(),
    onSuccess: () => {
      // Each active query reads again: me answers 401 and the shell
      // shows the landing page. The cached screens go with the session.
      void queryClient.resetQueries();
    },
  });

  return (
    <>
      <AccountRow
        headingId="closing-heading"
        title={accounts ? "Your data and account" : "Your data"}
      >
        <div className="account-action">
          <p id="download-hint" className="muted small">
            Every sketch and set of words you've sent, with your results for
            each revealed day, as one file.
          </p>
          <a
            className="btn btn-secondary"
            href={api.exportUrl()}
            download
            aria-describedby="download-hint"
          >
            Download my data
          </a>
        </div>
        {accounts ? (
          <>
            <div className="account-action">
              <p id="signout-hint" className="muted small">
                To sign back in, you'll need your username and password, or a
                code from another device.
              </p>
              <button
                type="button"
                className="btn btn-secondary"
                aria-describedby="signout-hint"
                disabled={signOut.isPending}
                onClick={() => signOut.mutate()}
              >
                Sign out of this device
              </button>
            </div>
            {me.has_password ? null : (
              <div className="notice notice-warn" role="note">
                <Warning size={18} aria-hidden="true" />
                <span>
                  This account has no password yet. Set one before you sign out,
                  or your only ways back in will be a code from another
                  signed-in device or a recovery code from the operator.
                </span>
              </div>
            )}
            {signOut.isError ? (
              <div className="notice notice-bad" role="alert">
                {friendlyMessage(signOut.error)}
              </div>
            ) : null}
            {identifier !== null ? null : (
              <div>
                <button
                  ref={deleteRow}
                  type="button"
                  className="account-delete-link"
                  aria-expanded={deleteOpen}
                  aria-controls={deleteOpen ? DELETE_PANEL_ID : undefined}
                  onClick={() => setDeleteOpen((open) => !open)}
                >
                  Delete account
                </button>
              </div>
            )}
          </>
        ) : null}
      </AccountRow>
      {!accounts ? null : identifier !== null ? (
        <section className="account-row" aria-label="Your account is deleted">
          <div className="account-row-title" />
          <div className="account-row-body">
            <div className="notice notice-good" role="status">
              Your account is deleted. Your earlier results show as {identifier}
              .
            </div>
            <div>
              <button
                type="button"
                className="btn btn-secondary"
                // Each query reads again: me answers 401 and the shell
                // shows the landing page.
                onClick={() => void queryClient.resetQueries()}
              >
                Done
              </button>
            </div>
          </div>
        </section>
      ) : deleteOpen ? (
        <DeleteAccountPanel
          me={me}
          onDeleted={setIdentifier}
          onClose={() => {
            setDeleteOpen(false);
            // The row opened the section, thus the keyboard goes back to it.
            deleteRow.current?.focus();
          }}
        />
      ) : null}
    </>
  );
}

const DELETE_PANEL_ID = "delete-panel";

/** What a deletion removes (spec MD1 §4.1, the `Goes` column). */
const DELETION_REMOVES: ReadonlyArray<string> = [
  "Your account and sign-in",
  "Your picture and description",
  "Your password and recovery code",
  "Every signed-in device",
];

/**
 * `Delete my account` (spec MD1 §4.3), the section that the
 * `Delete account` words open. It says what goes and what stays, and
 * that a published snapshot keeps the username. The player types the
 * username and the password; the red button stays off until the
 * username agrees. An account with no password sets one first.
 *
 * The section shows after a click on a row above it, thus focus moves
 * to its heading: a screen reader announces it and the keyboard starts
 * there.
 */
function DeleteAccountPanel(props: {
  me: MeView;
  onClose: () => void;
  /** Gets the anonymous name that the earlier results show. */
  onDeleted: (identifier: string) => void;
}): React.JSX.Element {
  const api = useApi();
  const { me, onClose, onDeleted } = props;
  const [typed, setTyped] = useState("");
  const [password, setPassword] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  const remove = useMutation({
    mutationFn: () => api.deleteAccount(typed, password),
    // The parent swaps this section for the deleted note, and the typed
    // password goes with the section's state.
    onSuccess: (answer) => onDeleted(answer.identifier),
  });

  return (
    <section
      id={DELETE_PANEL_ID}
      className="account-row account-delete"
      aria-labelledby="delete-heading"
    >
      <div className="account-row-title">
        <h2 id="delete-heading" ref={heading} tabIndex={-1}>
          Delete my account
        </h2>
        <p className="muted small">This can't be reversed.</p>
      </div>
      <div className="account-row-body">
        <div className="account-delete-columns">
          <div className="account-delete-column account-delete-removed">
            <h3 id="delete-removed-heading">Removed for good</h3>
            <ul aria-labelledby="delete-removed-heading">
              {DELETION_REMOVES.map((text) => (
                <li key={text}>
                  <X size={16} weight="bold" aria-hidden="true" />
                  <span>{text}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="account-delete-column account-delete-stays">
            <h3 id="delete-stays-heading">Stays public</h3>
            <ul aria-labelledby="delete-stays-heading">
              <li>
                <Eye size={16} aria-hidden="true" />
                <span>
                  Your past sketches, words, and results, under an anonymous
                  name with no picture
                </span>
              </li>
              <li>
                <Eye size={16} aria-hidden="true" />
                <span>Your username in any snapshot already published</span>
              </li>
              <li>
                <LockSimple size={16} aria-hidden="true" />
                <span>
                  The name {me.player} stays closed: nobody can register it
                  again, you included
                </span>
              </li>
            </ul>
          </div>
        </div>
        <div>
          <a className="foot-link" href={api.exportUrl()} download>
            <DownloadSimple size={18} aria-hidden="true" />
            Download my data first
          </a>
        </div>
        {me.has_password ? (
          <form
            className="stack"
            onSubmit={(event) => {
              event.preventDefault();
              if (typed === me.player && password !== "" && !remove.isPending) {
                remove.mutate();
              }
            }}
          >
            <div className="account-delete-fields">
              <div className="field">
                <label className="label" htmlFor="delete-username">
                  Type {me.player} to confirm
                </label>
                <input
                  id="delete-username"
                  className="input"
                  value={typed}
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(event) => setTyped(event.target.value)}
                />
              </div>
              <PasswordField
                id="delete-password"
                label="Password"
                autoComplete="current-password"
                value={password}
                onChange={setPassword}
              />
            </div>
            {remove.isError ? (
              <div className="notice notice-bad" role="alert">
                {credentialMessage(remove.error)}
              </div>
            ) : null}
            <div className="account-delete-actions">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={onClose}
              >
                Keep my account
              </button>
              <button
                type="submit"
                className="btn btn-danger-solid"
                disabled={
                  typed !== me.player || password === "" || remove.isPending
                }
              >
                {remove.isPending ? "Deleting…" : "Delete my account"}
              </button>
            </div>
          </form>
        ) : (
          <>
            <div className="notice notice-warn" role="note">
              <Warning size={18} aria-hidden="true" />
              <span>
                This account has no password yet. Set a password first, and then
                you can delete your account here. Or send the operator a
                message.
              </span>
            </div>
            <div className="account-delete-actions">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={onClose}
              >
                Keep my account
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
