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
import { DevApiError } from "./api";
import { utcStamp } from "./format";
import { storedOrigin } from "./invite-panel";
import type { DevDeviceCode, DevPlayerDetail, MintedInvite } from "./types";

function messageOf(error: unknown): string {
  return error instanceof DevApiError ? error.message : "refused";
}

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

  const act = async (
    action: () => Promise<Printed | null>,
    confirmText?: string,
  ) => {
    if (confirmText !== undefined && !window.confirm(confirmText)) {
      return;
    }
    setBusy(true);
    setPrinted(null);
    try {
      setPrinted(await action());
      await load();
      onChanged();
    } catch (error) {
      setPrinted({ kind: "note", text: messageOf(error) });
    } finally {
      setBusy(false);
    }
  };

  if (detail === null) {
    return (
      <p className="dev-muted" role="status">
        {note === "" ? "loading…" : note}
      </p>
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
            <strong className="dev-name">{detail.display_name}</strong>
            <span className="dev-muted">{detail.player}</span>
            <span
              className={`dev-status dev-status-${active ? "open" : "revoked"}`}
            >
              {detail.status}
            </span>
          </div>
          <span className="dev-muted">
            player since {utcStamp(detail.created_at)} ·{" "}
            {detail.sends === 1 ? "1 send" : `${detail.sends} sends`}
          </span>
          <p className="dev-description">
            {detail.description === "" ? (
              <span className="dev-muted">No description.</span>
            ) : (
              detail.description
            )}
          </p>
        </div>
      </div>

      <div className="dev-subhead">
        Devices signed in · {detail.sessions.length}
      </div>
      {detail.sessions.length === 0 ? (
        <p className="dev-muted">
          No device is signed in.
          {active
            ? " A new invite address or a device code lets the player back in."
            : ""}
        </p>
      ) : (
        <table className="table dev-table">
          <thead>
            <tr>
              <th>device</th>
              <th>signed in</th>
              <th>ends</th>
              <th>
                <span className="visually-hidden">action</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {detail.sessions.map((session) => (
              <tr key={session.id}>
                <td>{session.label}</td>
                <td>{utcStamp(session.created_at)}</td>
                <td>{utcStamp(session.ends_at)}</td>
                <td className="dev-num">
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
      )}
      {detail.device_codes.length === 0 ? null : (
        <p className="dev-muted">
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

      <div className="dev-subhead">Access</div>
      <div className="dev-row dev-wrap">
        {active ? (
          <>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={busy}
              onClick={() =>
                void act(
                  async () => ({
                    kind: "invite",
                    invite: await api.rotatePlayer(player),
                  }),
                  `Make a new invite address for ${player}? The old address stops working. Devices stay signed in.`,
                )
              }
            >
              New invite address
            </button>
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
            <button
              type="button"
              className="btn btn-secondary"
              disabled={busy || detail.sessions.length === 0}
              onClick={() =>
                void act(async () => {
                  const answer = await api.signOutPlayer(player);
                  return {
                    kind: "note",
                    text:
                      answer.ended === 1
                        ? "1 device is signed out."
                        : `${answer.ended} devices are signed out.`,
                  };
                }, `Sign ${player} out on every device?`)
              }
            >
              Sign out every device
            </button>
            <button
              type="button"
              className="btn btn-secondary dev-danger"
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  await api.revokePlayer(player);
                  return {
                    kind: "note",
                    text: `${player} is revoked: the invite address and each device stop working.`,
                  };
                }, `Revoke ${player}? Their invite address and every signed-in device stop working. Their play stays stored.`)
              }
            >
              Revoke access
            </button>
          </>
        ) : (
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy}
            onClick={() =>
              void act(
                async () => ({
                  kind: "invite",
                  invite: await api.restorePlayer(player),
                }),
                `Restore ${player}? They get a new invite address; no old device comes back.`,
              )
            }
          >
            Restore access
          </button>
        )}
      </div>

      {printed === null ? null : printed.kind === "note" ? (
        <p className="dev-muted" role="status">
          {printed.text}
        </p>
      ) : printed.kind === "invite" ? (
        <div className="dev-printed" role="status">
          <span>New invite address for {printed.invite.player}:</span>
          <code className="dev-break" data-testid="account-invite-url">
            {origin}
            {printed.invite.join_path}
          </code>
          <span className="dev-hint">
            This is the one time it prints. The origin comes from the invite
            panel above.
          </span>
        </div>
      ) : (
        <div className="dev-printed" role="status">
          <span>Device code for {printed.code.player}:</span>
          <code className="dev-device-code" data-testid="account-device-code">
            {printed.code.display}
          </code>
          <span className="dev-hint">
            The player types it on the device's sign-in page. It works one time
            and expires {utcStamp(printed.code.expires_at)}.
          </span>
        </div>
      )}
    </section>
  );
}
