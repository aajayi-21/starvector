/**
 * The two ways in with no password, as rows that open below the
 * sign-in form: a device code (spec A2 §3.5) and, on a dev server, the
 * open door (spec A1 §4). Each row stays closed until the player
 * opens it, thus the card reads as one sign-in form.
 */

import { CaretRight } from "@phosphor-icons/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useApi } from "../api/client";
import { friendlyMessage, isRefusal } from "../api/types";

/**
 * The device code (spec A2 §3.5): a signed-in device makes a code of
 * 8 characters, and this device types it. No password is typed.
 */
export function DeviceCodeRow(props: {
  onSignedIn: () => void;
}): React.JSX.Element {
  const api = useApi();
  const [code, setCode] = useState("");
  const redeem = useMutation({
    mutationFn: () => api.redeemDeviceCode(code),
    onSuccess: props.onSignedIn,
  });
  const typed = code.replaceAll(/[\s-]/g, "");
  return (
    <details className="row-disclosure">
      <summary>
        <span>Use a code from another device</span>
        <CaretRight
          className="row-chevron gate-chevron"
          size={16}
          aria-hidden="true"
        />
      </summary>
      <form
        className="row-body"
        onSubmit={(event) => {
          event.preventDefault();
          if (typed.length === 8 && !redeem.isPending) {
            redeem.mutate();
          }
        }}
      >
        <p className="hint" id="device-code-hint">
          Already signed in somewhere else? On that device, open your account
          and choose “Add a device”, then type the 8-character code here. You
          won't need your password.
        </p>
        <div className="field">
          <label className="label" htmlFor="device-code">
            Device code
          </label>
          <div className="gate-inline-form">
            <input
              id="device-code"
              className="input gate-code-input"
              aria-describedby="device-code-hint"
              placeholder="ABCD-EFGH"
              autoComplete="one-time-code"
              autoCapitalize="characters"
              spellCheck={false}
              maxLength={12}
              value={code}
              onChange={(event) => setCode(event.target.value)}
            />
            <button
              type="submit"
              className="btn btn-secondary"
              disabled={typed.length !== 8 || redeem.isPending}
            >
              {redeem.isPending ? "Signing in…" : "Use this code"}
            </button>
          </div>
        </div>
        {redeem.isError ? (
          <div className="notice notice-bad" role="alert">
            {friendlyMessage(redeem.error)}
          </div>
        ) : null}
      </form>
    </details>
  );
}

/**
 * The open door of a dev server (spec A1 §4): a typed name and the
 * operator token become a session. The gate shows the row only when
 * `GET /api/door` said the door is open.
 */
export function DoorRow(): React.JSX.Element {
  const api = useApi();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [token, setToken] = useState("");

  const enter = useMutation({
    // No display name: the username is the one name (spec A2 ruling 3).
    mutationFn: () => api.postDoor(name.trim(), undefined, token),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });

  return (
    <details className="row-disclosure">
      <summary>
        <span className="gate-row-title">
          <span>Operator sign-in</span>
          <span className="badge badge-warn">Test server</span>
        </span>
        <CaretRight
          className="row-chevron gate-chevron"
          size={16}
          aria-hidden="true"
        />
      </summary>
      <form
        className="row-body"
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim() !== "" && !enter.isPending) {
            enter.mutate();
          }
        }}
      >
        <p className="hint">
          This is a test server, so the operator can sign in with a name and the
          operator token instead of a password. Real servers don't show this.
        </p>
        <div className="field">
          <label className="label" htmlFor="door-name">
            Player name
          </label>
          <input
            id="door-name"
            className="input"
            placeholder="lowercase letters, digits, hyphens"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <div className="field">
          <label className="label" htmlFor="door-token">
            Operator token
          </label>
          <input
            id="door-token"
            className="input"
            type="password"
            autoComplete="off"
            value={token}
            onChange={(event) => setToken(event.target.value)}
          />
        </div>
        <button
          type="submit"
          className="btn btn-secondary btn-block"
          disabled={name.trim() === "" || enter.isPending}
        >
          {enter.isPending ? "Signing in…" : "Sign in by name"}
        </button>
        {enter.isError ? (
          <div className="notice notice-bad" role="alert">
            {isRefusal(enter.error)
              ? "Name sign-in needs the operator token on this server."
              : friendlyMessage(enter.error)}
          </div>
        ) : null}
      </form>
    </details>
  );
}
