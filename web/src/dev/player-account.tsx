/**
 * One player's account in the console (spec BR1 §7.4, changed by spec
 * A2 §6.1 and §10.1): the picture, the description, the signed-in
 * devices, the device codes that wait, and the access controls — a
 * recovery code, sign-out, revoke, and restore.
 *
 * The operator's recovery code is the one procedure into an account
 * that the console has. It prints one time: the store keeps its
 * digest alone, and it does not go to localStorage. It works 24 hours
 * after it is made, and the player's signed-in devices show a notice
 * with a control that stops it.
 */

import { useCallback, useEffect, useState } from "react";

import type { DevApi } from "./api";
import {
  ConfirmAction,
  ErrorNote,
  messageOf,
  StatusBadge,
  WorkingNote,
} from "./controls";
import { utcShort, utcStamp } from "./format";
import type { DevPlayerDetail, DevRecoveryCode } from "./types";

/** What the last access control printed, one time. */
type Printed =
  | { kind: "code"; code: DevRecoveryCode; restored: boolean }
  | { kind: "note"; text: string };

export function PlayerAccount(props: {
  api: DevApi;
  player: string;
  /** Tells the roster a count moved (devices, status). */
  onChanged: () => void;
}): React.JSX.Element {
  const { api, player, onChanged } = props;
  const [detail, setDetail] = useState<DevPlayerDetail | null>(null);
  const [note, setNote] = useState("");
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [printed, setPrinted] = useState<Printed | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setDetail(await api.getPlayer(player));
      setNote("");
    } catch (error) {
      setNote(messageOf(error));
    }
  }, [api, player]);

  useEffect(() => {
    setDetail(null);
    setPrinted(null);
    setError("");
    void load();
  }, [load]);

  // The picture comes through fetch with the bearer; the object URL is
  // released when the player or the picture changes.
  const hasAvatar = detail?.has_avatar === true;
  const updatedAt = detail?.account_updated_at ?? null;
  useEffect(() => {
    void updatedAt;
    if (!hasAvatar) {
      setAvatarUrl(null);
      return;
    }
    let url: string | null = null;
    let live = true;
    api
      .getAvatar(player)
      .then((blob) => {
        if (live && blob !== null) {
          url = URL.createObjectURL(blob);
          setAvatarUrl(url);
        }
      })
      .catch(() => {
        if (live) {
          setAvatarUrl(null);
        }
      });
    return () => {
      live = false;
      if (url !== null) {
        URL.revokeObjectURL(url);
      }
    };
  }, [api, player, hasAvatar, updatedAt]);

  const act = async (action: () => Promise<Printed>) => {
    setBusy(true);
    setPrinted(null);
    setError("");
    try {
      setPrinted(await action());
      await load();
      onChanged();
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  };

  if (detail === null) {
    return note === "" ? (
      <p className="subtle small" role="status">
        loading…
      </p>
    ) : (
      <ErrorNote text={note} />
    );
  }

  const active = detail.status === "active";

  return (
    <section className="dev-account" aria-label={`${player} account`}>
      <div className="dev-row dev-top">
        {avatarUrl === null ? (
          <span className="dev-avatar dev-avatar-empty" aria-hidden="true">
            {detail.player.slice(0, 2).toUpperCase()}
          </span>
        ) : (
          <img className="dev-avatar" src={avatarUrl} alt={detail.player} />
        )}
        <div className="dev-stack-sm">
          <div className="dev-row dev-wrap">
            {/* The username is the one name on a board (spec A2
                ruling 3). A label from before that spec stays in its
                record and shows here alone. */}
            <h3 className="dev-name">{detail.player}</h3>
            {detail.display_name === detail.player ? null : (
              <span className="subtle">
                earlier label: {detail.display_name}
              </span>
            )}
            <StatusBadge status={detail.status} />
          </div>
          <span className="muted small">
            Player since {utcStamp(detail.created_at)} ·{" "}
            {detail.sends === 1 ? "1 send" : `${detail.sends} sends`} ·{" "}
            <span data-testid="account-has-password">
              {detail.has_password ? "has a password" : "no password set"}
            </span>
          </span>
          <p className="dev-description">
            {detail.description === "" ? (
              <span className="subtle">No description.</span>
            ) : (
              detail.description
            )}
          </p>
        </div>
      </div>

      <div className="dev-subhead">Access</div>
      <div className="dev-row dev-wrap dev-top">
        {active ? (
          <>
            <ConfirmAction
              label="Recovery code"
              question={`Make a recovery code for ${player}? It works only after 24 hours, and until then each signed-in device of ${player} shows a notice with a control that stops it. Their password, their own recovery code, and their devices stay as they are. Give a code only to the person the account belongs to.`}
              confirmLabel="Yes, make a recovery code"
              disabled={busy}
              onConfirm={() =>
                void act(async () => ({
                  kind: "code",
                  code: await api.issueRecoveryCode(player),
                  restored: false,
                }))
              }
            />
            <ConfirmAction
              label="Sign out every device"
              question={`Sign ${player} out on every device?`}
              confirmLabel="Yes, sign out"
              variant="secondary"
              disabled={busy || detail.sessions.length === 0}
              onConfirm={() =>
                void act(async () => {
                  const answer = await api.signOutPlayer(player);
                  return {
                    kind: "note",
                    text:
                      answer.ended === 1
                        ? "1 device is signed out."
                        : `${answer.ended} devices are signed out.`,
                  };
                })
              }
            />
            <ConfirmAction
              label="Revoke access"
              question={`Revoke ${player}? Every signed-in device stops working, and the password and each recovery code sign nobody in. Their play stays stored.`}
              confirmLabel="Yes, revoke"
              variant="danger"
              disabled={busy}
              onConfirm={() =>
                void act(async () => {
                  await api.revokePlayer(player);
                  return {
                    kind: "note",
                    text: `${player} is revoked: each device, the password, and each recovery code stop working.`,
                  };
                })
              }
            />
          </>
        ) : (
          <ConfirmAction
            label="Restore access"
            question={`Restore ${player}? The account is active again and you get a recovery code for them, which works only after 24 hours. No old device comes back.`}
            confirmLabel="Yes, restore"
            disabled={busy}
            onConfirm={() =>
              void act(async () => ({
                kind: "code",
                code: await api.restorePlayer(player),
                restored: true,
              }))
            }
          />
        )}
      </div>
      <p className="subtle small">
        {active
          ? "A player signs in with their username and password. A recovery code is for a player with no password and no signed-in device: they use it under “I do not have my password” on the sign-in page."
          : "A revoked player cannot sign in. Restoring makes the account active and gives you a recovery code for them."}
      </p>
      {detail.operator_code === null ? null : (
        <div className="notice" role="note" data-testid="account-operator-code">
          An operator's recovery code is live for {player}: made{" "}
          {utcStamp(detail.operator_code.issued_at)}, works from{" "}
          {utcStamp(detail.operator_code.usable_at)}. Their signed-in devices
          show a notice, and the player can stop it.
        </div>
      )}

      {busy ? <WorkingNote text="Working…" /> : null}
      <ErrorNote text={error} />
      {printed === null ? null : printed.kind === "note" ? (
        <div className="notice notice-good" role="status">
          {printed.text}
        </div>
      ) : (
        <div className="dev-printed" role="status">
          <span className="small">
            {printed.restored
              ? `${printed.code.player} is active again. Recovery code for ${printed.code.player}:`
              : `Recovery code for ${printed.code.player}:`}
          </span>
          <code
            className="dev-recovery-code dev-break"
            data-testid="account-recovery-code"
          >
            {printed.code.recovery_code}
          </code>
          <CopyButton text={printed.code.recovery_code} />
          <span className="small">
            <strong>
              It works only from {utcStamp(printed.code.usable_at)}.
            </strong>{" "}
            Before that time a recovery with it is refused. Until it is used,
            each signed-in device of {printed.code.player} shows a notice with a
            “Stop this” control.
          </span>
          <span className="subtle small">
            This is the one time it prints: the store keeps only a digest. Copy
            it and give it to the player by hand. They type it under “I do not
            have my password” with a new password, and it works one time.
          </span>
        </div>
      )}

      <div className="dev-subhead">
        Devices signed in · {detail.sessions.length}
      </div>
      {detail.sessions.length === 0 ? (
        <p className="muted small">No device is signed in.</p>
      ) : (
        <div className="dev-scroll-x">
          <table className="table dev-table">
            <thead>
              <tr>
                <th>device</th>
                <th>signed in (UTC)</th>
                <th>ends (UTC)</th>
                <th>
                  <span className="visually-hidden">action</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {detail.sessions.map((session) => (
                <tr key={session.id}>
                  <td>{session.label}</td>
                  <td>{utcShort(session.created_at)}</td>
                  <td>{utcShort(session.ends_at)}</td>
                  <td className="num">
                    <button
                      type="button"
                      className="btn btn-ghost"
                      disabled={busy}
                      onClick={() =>
                        void act(async () => {
                          await api.endSession(player, session.id);
                          return {
                            kind: "note",
                            text: `${session.label} is signed out.`,
                          };
                        })
                      }
                    >
                      Sign out
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {detail.device_codes.length === 0 ? null : (
        <p className="muted small">
          {detail.device_codes.length === 1
            ? "1 device code waits"
            : `${detail.device_codes.length} device codes wait`}{" "}
          — the last expires{" "}
          {utcStamp(
            detail.device_codes[detail.device_codes.length - 1]?.expires_at,
          )}
          .
        </p>
      )}
    </section>
  );
}

/** Copies one printed value, and says so. */
function CopyButton(props: { text: string }): React.JSX.Element {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="btn btn-secondary dev-copy"
      onClick={() => {
        navigator.clipboard
          ?.writeText(props.text)
          .then(() => setCopied(true))
          .catch(() => setCopied(false));
      }}
    >
      {copied ? "Copied" : "Copy the code"}
    </button>
  );
}
