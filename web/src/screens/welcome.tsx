/**
 * The signed-out landing page (spec BR1 §4, §6). It replaces the
 * invite gate of spec M1 §9, which had nothing to type and no way
 * back in. It renders on a 401 and on nothing else: a server that is
 * down is ApiError(0), and sending that reader to hunt for a link
 * takes them somewhere no link helps.
 *
 * Two ways in, both typed or opened on this device:
 * - the invite link, which the server turns into a session;
 * - a device code from a device that is signed in — the path that
 *   works in an iPhone home-screen app, which keeps its own cookies.
 *
 * On a dev server the open door (spec A1 §4) adds a name field.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useApi } from "../api/client";
import { friendlyMessage, isRefusal } from "../api/types";
import { LogoMark } from "../ui/logo";
import { HowItWorksSteps } from "./how";

export function WelcomeScreen(): React.JSX.Element {
  const api = useApi();
  const about = useQuery({
    queryKey: ["about"],
    queryFn: () => api.getAbout(),
    staleTime: Number.POSITIVE_INFINITY,
  });
  const door = useQuery({
    queryKey: ["door"],
    queryFn: () => api.getDoor(),
    retry: false,
  });
  const photoCount = about.data?.photo_count;
  return (
    <>
      <header className="topbar">
        <span className="brand">
          <LogoMark />
          Starvector
        </span>
      </header>
      {about.data?.test_season === true ? (
        <div className="season-note" role="note">
          Test season — invited players only. Results won't carry over to the
          public launch.
        </div>
      ) : null}
      <main className="page">
        <div className="home-hero" style={{ marginBottom: 40 }}>
          <div className="stack">
            <h1 style={{ fontSize: 36 }}>A new hidden photo every day.</h1>
            <p className="muted" style={{ fontSize: 18, maxWidth: 560 }}>
              Each day a photo is hidden behind a short code. You sketch and
              describe whatever comes to mind, and when the day closes you see
              the photo — and how close you came
              {photoCount === undefined
                ? "."
                : `, measured against ${photoCount} photos.`}
            </p>
          </div>
        </div>
        {/* Sign-in comes first in the page flow: on a phone it is the
            first card, and a home-screen app that opens signed out
            meets the code field at once. On a wide screen the grid
            puts it in the right column (app.css .welcome-grid). */}
        <div className="two-columns welcome-grid">
          <div className="stack welcome-signin">
            <SignInCard />
            {door.data?.open === true ? <DoorCard /> : null}
          </div>
          <section className="card" aria-labelledby="how-heading">
            <h2 id="how-heading">How it works</h2>
            <HowItWorksSteps />
          </section>
        </div>
      </main>
    </>
  );
}

function SignInCard(): React.JSX.Element {
  const api = useApi();
  const queryClient = useQueryClient();
  const [code, setCode] = useState("");
  const redeem = useMutation({
    mutationFn: () => api.redeemDeviceCode(code),
    onSuccess: () => {
      // The cookie came with the answer; the shell reads me again
      // and renders signed in.
      void queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });
  const typed = code.replaceAll(/[\s-]/g, "");
  return (
    <section className="card card-hero" aria-labelledby="signin-heading">
      <h2 id="signin-heading">Sign in</h2>
      <p className="muted">
        Starvector is invite-only for now. To sign in, open the invite link you
        were sent on this device.
      </p>
      <hr className="divider" />
      <form
        className="stack-sm"
        onSubmit={(event) => {
          event.preventDefault();
          if (typed.length === 8 && !redeem.isPending) {
            redeem.mutate();
          }
        }}
      >
        <label className="label" htmlFor="device-code">
          Signed in on another device?
        </label>
        <p className="hint" id="device-code-hint">
          On that device, open your account and choose “Add a device”. Then type
          the 8-character code here.
        </p>
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input
            id="device-code"
            className="input"
            aria-describedby="device-code-hint"
            placeholder="ABCD-EFGH"
            autoComplete="one-time-code"
            autoCapitalize="characters"
            spellCheck={false}
            maxLength={12}
            value={code}
            onChange={(event) => setCode(event.target.value)}
            style={{
              fontFamily: "var(--mono)",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
            }}
          />
          <button
            type="submit"
            className="btn btn-primary"
            disabled={typed.length !== 8 || redeem.isPending}
          >
            {redeem.isPending ? "Signing in…" : "Sign in"}
          </button>
        </div>
        {redeem.isError ? (
          <div className="notice notice-bad" role="alert">
            {friendlyMessage(redeem.error)}
          </div>
        ) : null}
      </form>
    </section>
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
      void queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });

  return (
    <section className="card card-quiet" aria-labelledby="door-heading">
      <h3 id="door-heading">Test server sign-in</h3>
      <p className="hint">
        This is a test server, so you can sign in with a name alone. Real
        servers don't show this.
      </p>
      <form
        className="stack-sm"
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim() !== "" && !enter.isPending) {
            enter.mutate();
          }
        }}
      >
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
        <label className="label" htmlFor="door-label">
          Display name <span className="subtle">(optional)</span>
        </label>
        <input
          id="door-label"
          className="input"
          value={label}
          onChange={(event) => setLabel(event.target.value)}
        />
        <button
          type="submit"
          className="btn btn-secondary"
          disabled={name.trim() === "" || enter.isPending}
        >
          {enter.isPending ? "Signing in…" : "Sign in by name"}
        </button>
        {enter.isError ? (
          <div className="notice notice-bad" role="alert">
            {isRefusal(enter.error)
              ? "Name sign-in is off on this server."
              : friendlyMessage(enter.error)}
          </div>
        ) : null}
      </form>
    </section>
  );
}
