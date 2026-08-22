/**
 * The account screen (spec A1 §3): the caller's own page. The
 * picture with a file input and a remove control, the display name
 * and the store key, the streak, and the description editor. The
 * writers write for the resolved caller alone — no player
 * parameter anywhere on this screen.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { useApi } from "../api/client";
import type { MeView } from "../api/types";
import { friendlyMessage } from "../api/types";
import { AvatarCircle } from "../ui/avatar";
import { downscaleImage } from "../ui/downscale";
import { Kicker } from "../ui/kicker";

/** The D1 cap, mirrored for the counter — the server owns the rule. */
const DESCRIPTION_LIMIT = 500;

export function AccountScreen(): React.JSX.Element {
  const api = useApi();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.getMe() });
  if (me.isPending) {
    return (
      <div style={{ padding: 28 }}>
        <p className="text-muted">Loading…</p>
      </div>
    );
  }
  if (me.isError || me.data === undefined) {
    return (
      <div style={{ padding: 28, maxWidth: 520 }}>
        <div className="card">
          <span className="card-kicker">Account</span>
          <p className="text-muted" role="alert">
            {friendlyMessage(me.error)}
          </p>
        </div>
      </div>
    );
  }
  return <AccountBody me={me.data} />;
}

function AccountBody(props: { me: MeView }): React.JSX.Element {
  const api = useApi();
  const queryClient = useQueryClient();
  const { me } = props;
  const fileRef = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState(me.description);
  const [savedNote, setSavedNote] = useState(false);

  const invalidateMe = () =>
    queryClient.invalidateQueries({ queryKey: ["me"] });

  const saveDescription = useMutation({
    mutationFn: (text: string) => api.putAccount(text),
    onSuccess: () => {
      setSavedNote(true);
      void invalidateMe();
    },
  });

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
    <div
      style={{
        padding: 28,
        maxWidth: 560,
        display: "flex",
        flexDirection: "column",
        gap: 14,
      }}
    >
      <div className="card elev-sm" style={{ gap: 12 }}>
        <Kicker>Your account</Kicker>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <AvatarCircle
            player={me.player}
            displayName={me.display_name}
            avatarHash={me.avatar_hash}
            size={96}
          />
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <div style={{ fontSize: 20, fontWeight: 500 }}>
              {me.display_name}
            </div>
            <div
              style={{
                fontSize: 12,
                color: "var(--color-neutral-500)",
                fontFamily: "ui-monospace, Menlo, monospace",
              }}
            >
              {me.player}
            </div>
            <div style={{ fontSize: 13 }}>
              <span className="tag tag-accent">streak {me.streak}</span>
            </div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            ref={fileRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            aria-label="pick a profile picture"
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
          <span style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
            Scaled to 256 px before it uploads.
          </span>
        </div>
        {avatarError === null ? null : (
          <div style={{ fontSize: 13, color: "#bf616a" }} role="alert">
            {friendlyMessage(avatarError)}
          </div>
        )}
      </div>

      <div className="card" style={{ gap: 10 }}>
        <Kicker>About you</Kicker>
        <textarea
          className="input"
          aria-label="account description"
          placeholder="a few lines about yourself"
          value={draft}
          maxLength={DESCRIPTION_LIMIT}
          onChange={(event) => {
            setDraft(event.target.value);
            setSavedNote(false);
          }}
          style={{ minHeight: 96 }}
        />
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
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
          <span style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
            {savedNote ? "saved" : `${draft.length} of ${DESCRIPTION_LIMIT}`}
          </span>
        </div>
        {saveDescription.isError ? (
          <div style={{ fontSize: 13, color: "#bf616a" }} role="alert">
            {friendlyMessage(saveDescription.error)}
          </div>
        ) : null}
      </div>
    </div>
  );
}
