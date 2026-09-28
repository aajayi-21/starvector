/**
 * The account screen (spec A1 §3, grown by spec BR1 §4–5): the
 * picture and the description, the signed-in devices with "Add a
 * device" and sign-out, and the data download. The writers write for
 * the resolved caller alone — no player parameter on this screen.
 *
 * A server with no accounts (spec M1 ruling 7) lists no session: the
 * device and sign-out sections then say so instead of offering
 * moves that do nothing.
 */

import { DeviceMobile, Laptop } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { useApi } from "../api/client";
import type { DeviceCodeView, MeView, SessionRow } from "../api/types";
import { friendlyMessage } from "../api/types";
import { AvatarCircle } from "../ui/avatar";
import { useNow } from "../ui/countdown";
import { downscaleImage } from "../ui/downscale";
import { formatInstantDay, formatRemaining } from "../ui/format";

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
      {accounts === true ? <SignOutCard /> : null}
    </div>
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
          displayName={me.display_name}
          avatarHash={me.avatar_hash}
          size={88}
        />
        <div className="stack-sm">
          <h2 style={{ fontSize: 24 }}>{me.display_name}</h2>
          <span className="subtle small">Player id: {me.player}</span>
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
            On your other device, open Starvector and choose “Signed in on
            another device?”. Then type this code:
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

function SignOutCard(): React.JSX.Element {
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
        Sign out of this device. To sign back in, open your invite link again or
        use a code from another device.
      </p>
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
