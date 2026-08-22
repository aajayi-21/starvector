/**
 * The invite gate (spec M1 §9), grown by the open door (spec A1
 * §4).
 *
 * The session cookie rides same-origin calls, so the client holds
 * no credential and the invite path has no field to type into.
 * What the card has to say is that an invite link is the way in.
 *
 * It renders on a 401 and on nothing else. A server that is down
 * is ApiError(0) and a broken server is a 500; sending either of
 * those readers to hunt for a link takes them somewhere no link
 * helps.
 *
 * The door: the gate probes GET /api/door once. On a dev server it
 * answers {open: true} and the card grows a name field — a typed
 * name becomes a session, no password, for test boxes alone. In
 * production the probe meets the constant 404 and the card stays
 * exactly what it was.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useApi } from "../api/client";
import { friendlyMessage, isRefusal } from "../api/types";

export function InviteGate(): React.JSX.Element {
  const api = useApi();
  const door = useQuery({
    queryKey: ["door"],
    queryFn: () => api.getDoor(),
    retry: false,
  });
  const doorOpen = door.data?.open === true;
  return (
    <div style={{ padding: 28, maxWidth: 520 }}>
      <div className="card" style={{ gap: 10 }}>
        <span className="card-kicker">Invite</span>
        <p style={{ margin: 0 }}>This browser is not signed in.</p>
        <p className="text-muted" style={{ margin: 0 }}>
          Starvector is invite only. Open the invite link you were sent and this
          device stays signed in from then on — there is no password to keep,
          and nothing to type here.
        </p>
      </div>
      {doorOpen ? <DoorCard /> : null}
    </div>
  );
}

function DoorCard(): React.JSX.Element {
  const api = useApi();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");

  const enter = useMutation({
    mutationFn: () =>
      api.postDoor(name.trim(), label.trim() === "" ? undefined : label.trim()),
    onSuccess: () => {
      // The cookie landed with the answer; the shell re-reads me
      // and renders signed in.
      void queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });

  return (
    <div className="card" style={{ gap: 10, marginTop: 14 }}>
      <span className="card-kicker">Dev door</span>
      <p className="text-muted" style={{ margin: 0, fontSize: 13 }}>
        This is a development server, so the door is open: type a name to create
        an account or sign back in. No password — test boxes only.
      </p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input
          className="input"
          aria-label="player name"
          placeholder="player name (a-z, 0-9, -)"
          style={{ width: 200 }}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <input
          className="input"
          aria-label="display name"
          placeholder="display name (optional)"
          style={{ width: 200 }}
          value={label}
          onChange={(event) => setLabel(event.target.value)}
        />
        <button
          type="button"
          className="btn btn-primary"
          disabled={name.trim() === "" || enter.isPending}
          onClick={() => enter.mutate()}
        >
          {enter.isPending ? "Entering…" : "Create or sign in"}
        </button>
      </div>
      {enter.isError ? (
        <p
          className="text-muted"
          role="alert"
          style={{ margin: 0, fontSize: 13 }}
        >
          {isRefusal(enter.error)
            ? "The door is not open on this server."
            : friendlyMessage(enter.error)}
        </p>
      ) : null}
    </div>
  );
}
