/**
 * One player's account in the console (spec BR1 §7.4): the picture,
 * the description, the signed-in devices, the device codes that
 * wait, and the access controls — a new invite address, a device
 * code, sign-out, revoke, and restore.
 *
 * A new invite address and a device code print one time, like the
 * mint: the store keeps digests alone. Neither goes to localStorage.
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
import { storedOrigin } from "./invite-panel";
import type { DevDeviceCode, DevPlayerDetail, MintedInvite } from "./types";

/** What the last access control printed, one time. */
type Printed =
  | { kind: "invite"; invite: MintedInvite }
  | { kind: "code"; code: DevDeviceCode }
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
  const origin = storedOrigin().replace(/\/+$/, "");

  return (
    <section className="dev-account" aria-label={`${player} account`}>
      <div className="dev-row dev-top">
        {avatarUrl === null ? (
          <span className="dev-avatar dev-avatar-empty" aria-hidden="true">
            {detail.display_name.slice(0, 2).toUpperCase()}
          </span>
        ) : (
          <img
            className="dev-avatar"
            src={avatarUrl}
            alt={detail.display_name}
          />
        )}
        <div className="dev-stack-sm">
          <div className="dev-row dev-wrap">
            <h3 className="dev-name">{detail.display_name}</h3>
            <span className="subtle">{detail.player}</span>
            <StatusBadge status={detail.status} />
          </div>
          <span className="muted small">
            Player since {utcStamp(detail.created_at)} ·{" "}
            {detail.sends === 1 ? "1 send" : `${detail.sends} sends`}
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
              label="New invite address"
              question={`Make a new invite address for ${player}? The old address stops working; signed-in devices stay signed in.`}
              confirmLabel="Yes, make a new address"
              disabled={busy}
              onConfirm={() =>
                void act(async () => ({
                  kind: "invite",
                  invite: await api.rotatePlayer(player),
                }))
              }
            />
            <button
              type="button"
              className="btn btn-secondary"
              disabled={busy}
              onClick={() =>
                void act(async () => ({
                  kind: "code",
                  code: await api.issueDeviceCode(player),
                }))
              }
            >
              Device code
            </button>
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
              question={`Revoke ${player}? Their invite address and every signed-in device stop working. Their play stays stored.`}
              confirmLabel="Yes, revoke"
              variant="danger"
              disabled={busy}
              onConfirm={() =>
                void act(async () => {
                  await api.revokePlayer(player);
                  return {
                    kind: "note",
                    text: `${player} is revoked: the invite address and each device stop working.`,
                  };
                })
              }
            />
          </>
        ) : (
          <ConfirmAction
            label="Restore access"
            question={`Restore ${player}? They get a new invite address; no old device comes back.`}
            confirmLabel="Yes, restore"
            disabled={busy}
            onConfirm={() =>
              void act(async () => ({
                kind: "invite",
                invite: await api.restorePlayer(player),
              }))
            }
          />
        )}
      </div>
      <p className="subtle small">
        {active
          ? "A new invite address signs in any device that opens it. A device code is for the iPhone home-screen app, where a link opens in Safari instead."
          : "A revoked player cannot sign in. Restoring gives them a new invite address."}
      </p>

      {busy ? <WorkingNote text="Working…" /> : null}
      <ErrorNote text={error} />
      {printed === null ? null : printed.kind === "note" ? (
        <div className="notice notice-good" role="status">
          {printed.text}
        </div>
      ) : printed.kind === "invite" ? (
        <div className="dev-printed" role="status">
          <span className="small">
            New invite address for {printed.invite.player}:
          </span>
          <code className="dev-break" data-testid="account-invite-url">
            {origin}
            {printed.invite.join_path}
          </code>
          <CopyButton text={`${origin}${printed.invite.join_path}`} />
          <span className="subtle small">
            This is the one time it prints — copy it and send it to the player.
            The site address comes from the invite panel above.
          </span>
        </div>
      ) : (
        <div className="dev-printed" role="status">
          <span className="small">Device code for {printed.code.player}:</span>
          <code className="dev-device-code" data-testid="account-device-code">
            {printed.code.display}
          </code>
          <span className="subtle small">
            The player types it on the app's sign-in page. It works one time and
            expires {utcStamp(printed.code.expires_at)}.
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
      {copied ? "Copied" : "Copy the address"}
    </button>
  );
}
