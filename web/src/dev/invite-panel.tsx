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
import { ErrorNote } from "./controls";
import type { MintedInvite } from "./types";

/** Where the invite origin is kept between visits. */
export const ORIGIN_KEY = "sv:dev:origin";

/** The invite origin the operator last typed, or this page's own. */
export function storedOrigin(): string {
  try {
    return window.localStorage.getItem(ORIGIN_KEY) ?? window.location.origin;
  } catch {
    return window.location.origin;
  }
}

export function InvitePanel(props: {
  api: DevApi;
  /** Tells the roster a player was added. */
  onMinted?: () => void;
}): React.JSX.Element {
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
      props.onMinted?.();
    } catch (error) {
      setNote(error instanceof DevApiError ? error.message : "refused");
    } finally {
      setWorking(false);
    }
  };

  // An invite that names the console's own address works for nobody:
  // the console is reached through a tunnel at localhost.
  const local = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/i.test(
    origin.trim(),
  );
  const invite =
    minted === null
      ? ""
      : `${origin.trim().replace(/\/+$/, "")}${minted.join_path}`;

  return (
    <div className="card" id="invite-panel">
      <div className="eyebrow">Invite a player</div>
      <div className="dev-form">
        <label className="field">
          <span className="label">Player name</span>
          <input
            className="input"
            placeholder="lowercase letters, digits, hyphens"
            value={player}
            onChange={(event) => setPlayer(event.target.value)}
          />
        </label>
        <label className="field">
          <span className="label">
            Display name <span className="subtle">(optional)</span>
          </span>
          <input
            className="input"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
          />
        </label>
        <label className="field dev-form-wide">
          <span className="label">Site address in the invite</span>
          <input
            className="input"
            placeholder="https://your-site"
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
        </label>
      </div>
      {local ? (
        <div className="notice" role="note">
          This is the console's own address. Players can't open it — put the
          public address of your site here, like https://your-domain.com.
        </div>
      ) : null}
      <div className="dev-row dev-wrap">
        <button
          type="button"
          className="btn btn-primary"
          disabled={player.trim() === "" || working}
          onClick={() => void mint()}
        >
          {working ? "Minting…" : "Mint the invite"}
        </button>
        <span className="subtle small">
          The invite prints one time. Copy it and send it to the player.
        </span>
      </div>
      <ErrorNote text={note} />
      {minted === null ? null : (
        <div className="dev-printed" role="status">
          <span className="small">
            Invite for {minted.display_name}
            {minted.display_name === minted.player ? "" : ` (${minted.player})`}
            :
          </span>
          <code className="dev-break" data-testid="invite-url">
            {invite}
          </code>
          <span className="subtle small">
            This is the one time it prints: the store keeps only a digest. If it
            gets lost, open the player below and make a new invite address.
          </span>
        </div>
      )}
    </div>
  );
}
