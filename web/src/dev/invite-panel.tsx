/**
 * The invite minter (spec M1 §8: "the console reads it").
 *
 * The operator plane's counterpart to `python -m service.players
 * mint`. The command-line path stays — it runs on the box and
 * wants no console — and this is the same act for an operator who
 * already has the console open.
 *
 * Two properties the copy has to hold.
 *
 * **The token prints once.** The store keeps its digest alone, so
 * no later read recovers it. A minted invite is therefore never
 * put in localStorage and never re-fetched: if the operator loses
 * it, the answer is `rotate`, not a lookup.
 *
 * **The origin is asked for, not assumed.** `join_path` is a path
 * because the server does not know its public address and must
 * not trust the Host header for one. The console cannot assume its
 * own address either: it is reached through an SSH tunnel at
 * localhost, while the invite has to name the public site. So the
 * field is offered with the current origin as a starting point and
 * the operator corrects it.
 */

import { useState } from "react";

import type { DevApi } from "./api";
import { DevApiError } from "./api";
import type { MintedInvite } from "./types";

/** Where the invite origin is kept between visits. */
export const ORIGIN_KEY = "sv:dev:origin";

function storedOrigin(): string {
  try {
    return window.localStorage.getItem(ORIGIN_KEY) ?? window.location.origin;
  } catch {
    return window.location.origin;
  }
}

export function InvitePanel(props: { api: DevApi }): React.JSX.Element {
  const [player, setPlayer] = useState("");
  const [label, setLabel] = useState("");
  const [origin, setOrigin] = useState(storedOrigin);
  const [minted, setMinted] = useState<MintedInvite | null>(null);
  const [note, setNote] = useState("");
  const [working, setWorking] = useState(false);

  const mint = async () => {
    setWorking(true);
    setNote("");
    setMinted(null);
    try {
      setMinted(await props.api.mintPlayer(player, label || player));
      setPlayer("");
      setLabel("");
    } catch (error) {
      setNote(error instanceof DevApiError ? error.message : "refused");
    } finally {
      setWorking(false);
    }
  };

  return (
    <div className="card" style={{ gap: 10 }} id="invite-panel">
      <span className="card-kicker">Invite a player</span>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input
          className="input"
          aria-label="player name"
          placeholder="player name (a-z, 0-9, -)"
          style={{ width: 220 }}
          value={player}
          onChange={(event) => setPlayer(event.target.value)}
        />
        <input
          className="input"
          aria-label="display name"
          placeholder="display name (optional)"
          style={{ width: 220 }}
          value={label}
          onChange={(event) => setLabel(event.target.value)}
        />
        <input
          className="input"
          aria-label="invite origin"
          placeholder="https://the-site"
          style={{ width: 240 }}
          value={origin}
          onChange={(event) => {
            setOrigin(event.target.value);
            try {
              window.localStorage.setItem(ORIGIN_KEY, event.target.value);
            } catch {
              // Storage refused: the origin still holds this visit.
            }
          }}
        />
        <button
          type="button"
          className="btn btn-primary"
          disabled={player.trim() === "" || working}
          onClick={() => void mint()}
        >
          {working ? "minting…" : "Mint the invite"}
        </button>
      </div>
      {note === "" ? null : (
        <p className="text-muted" role="alert" style={{ margin: 0 }}>
          {note}
        </p>
      )}
      {minted === null ? null : (
        <div
          style={{
            border: "1px dashed var(--color-accent)",
            borderRadius: 8,
            padding: "10px 12px",
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          <div style={{ fontSize: 13 }}>
            {minted.player} · {minted.display_name}
          </div>
          <code
            style={{ wordBreak: "break-all", fontSize: 13 }}
            data-testid="invite-url"
          >
            {origin.replace(/\/+$/, "")}
            {minted.join_path}
          </code>
          <span style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
            This is the one time the invite prints. Send it, then forget it —
            the store keeps only its digest, so a lost invite wants a rotate and
            not a lookup.
          </span>
        </div>
      )}
      <span style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
        The origin names the site the player will open, which is not this
        console's address when you reach it through the tunnel.
      </span>
    </div>
  );
}
