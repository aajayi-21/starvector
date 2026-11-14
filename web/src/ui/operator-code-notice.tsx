/**
 * The notice of an operator's recovery code (spec A2 §6.1). While such
 * a code is live, each signed-in device of the player shows this
 * banner on each screen, with the two times of the code and a `Stop
 * this` control. The control removes the code and asks for no
 * password: a session is sufficient to remove a code.
 *
 * The banner holds no code and no digest. `me` gives the two times
 * alone.
 */

import { ShieldWarning } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useApi } from "../api/client";
import { friendlyMessage } from "../api/types";
import { useNow } from "./countdown";
import { formatInstant } from "./format";

export function OperatorCodeNotice(): React.JSX.Element | null {
  const api = useApi();
  const queryClient = useQueryClient();
  // The key the shell and the top bar read: no second request.
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.getMe() });
  const now = useNow();
  const stop = useMutation({
    mutationFn: () => api.stopOperatorCode(),
    // me is read again, and the banner goes with the code.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["me"] }),
  });
  const code = me.data?.operator_code ?? null;
  if (code === null) {
    return null;
  }
  const usable = Date.parse(code.usable_at);
  const working = !Number.isNaN(usable) && usable <= now;
  return (
    <div className="operator-notice" role="alert">
      <div className="operator-notice-body">
        <ShieldWarning size={24} aria-hidden="true" />
        <p className="operator-notice-text">
          <strong>
            A recovery code was made for your account by the operator on{" "}
            {formatInstant(code.issued_at)}.
          </strong>{" "}
          {working
            ? `It has worked since ${formatInstant(code.usable_at)}.`
            : `It starts working at ${formatInstant(code.usable_at)}.`}{" "}
          If you did not ask for this, stop it.
        </p>
        <button
          type="button"
          className="btn btn-danger"
          disabled={stop.isPending}
          onClick={() => stop.mutate()}
        >
          {stop.isPending ? "Stopping…" : "Stop this"}
        </button>
        {stop.isError ? (
          <span className="small" style={{ color: "var(--bad)" }}>
            {friendlyMessage(stop.error)}
          </span>
        ) : null}
      </div>
    </div>
  );
}
