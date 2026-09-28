/**
 * The Players tab (spec BR1 §7.4): the invite minter, the roster with
 * each player's devices and account, and the prune of expired
 * sign-ins.
 */

import { useState } from "react";

import type { DevApi } from "./api";
import { DevApiError } from "./api";
import { InvitePanel } from "./invite-panel";
import { RosterPanel } from "./roster-panel";

export function PlayersTab(props: {
  api: DevApi;
  reload: number;
}): React.JSX.Element {
  const { api, reload } = props;
  // A mint or a prune moves the roster; the count is added to the
  // console's own reload, so either one reads the roster again.
  const [local, setLocal] = useState(0);
  const [pruneNote, setPruneNote] = useState("");
  const [pruning, setPruning] = useState(false);

  const prune = async () => {
    setPruning(true);
    setPruneNote("");
    try {
      const counts = await api.prune();
      setPruneNote(
        `Removed ${counts.sessions} expired ${
          counts.sessions === 1 ? "sign-in" : "sign-ins"
        } and ${counts.device_codes} expired device ${
          counts.device_codes === 1 ? "code" : "codes"
        }.`,
      );
      setLocal((count) => count + 1);
    } catch (error) {
      setPruneNote(error instanceof DevApiError ? error.message : "refused");
    } finally {
      setPruning(false);
    }
  };

  return (
    <div className="dev-stack">
      <InvitePanel api={api} onMinted={() => setLocal((count) => count + 1)} />
      <RosterPanel api={api} reload={reload + local} />
      <section className="card dev-card" aria-label="Expired sign-ins">
        <div className="dev-row dev-wrap">
          <button
            type="button"
            className="btn btn-secondary"
            disabled={pruning}
            onClick={() => void prune()}
          >
            Remove expired sign-ins
          </button>
          <span className="dev-hint">
            {pruneNote === ""
              ? "Sessions older than 180 days and device codes past their 10 minutes stop working on their own; this removes their files."
              : pruneNote}
          </span>
        </div>
      </section>
    </div>
  );
}
