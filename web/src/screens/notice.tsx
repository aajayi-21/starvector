/**
 * The blocking notice screen (spec R1 §3.2 and §3.3). A signed-in
 * player on a server that publishes results, with no agreement to the
 * current notice, gets this screen in place of the app: the notice
 * text, `I agree`, and a way to sign out. It is what a player sees one
 * time when the notice text changes (decision D2).
 *
 * `I agree` sends the version number this page was built with. When
 * that number is not the server's current one, the page cannot show
 * the text the player must agree to, thus it offers a reload and no
 * agreement.
 *
 * The screen holds no draft. A sketch the player was drawing stays in
 * this device's storage, and the drawing screen brings it back.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { useApi } from "../api/client";
import type { NoticeView } from "../api/types";
import { ApiError, friendlyMessage } from "../api/types";
import { hasUnsentDraft } from "../intake/drafts";
import { NOTICE_VERSION } from "../signin/notice";
import { NoticeText, OutOfDate } from "../signin/notice-text";
import { LogoMark } from "../ui/logo";
import { OfflineBanner } from "../ui/offline-banner";
import { OperatorCodeNotice } from "../ui/operator-code-notice";

/** True when a send of this player needs an agreement that is not there. */
export function needsAgreement(notice: NoticeView): boolean {
  return notice.required && !notice.agreed;
}

/** The 409 of a consent POST that names a version that is not current. */
function isRefusedVersion(error: unknown): boolean {
  return error instanceof ApiError && error.refusalCause === "notice-version";
}

export function NoticeScreen(props: { notice: NoticeView }): React.JSX.Element {
  const api = useApi();
  const queryClient = useQueryClient();
  const heading = useRef<HTMLHeadingElement>(null);
  const [draftKept, setDraftKept] = useState(false);

  // The screen replaces the app: focus moves to its heading, thus a
  // screen reader announces it. The draft read is in the same effect
  // because the drawing screen saves its sketch as it leaves the page,
  // and that save runs before this effect and after this render.
  useEffect(() => {
    heading.current?.focus();
    setDraftKept(hasUnsentDraft());
  }, []);

  const readMe = () => queryClient.invalidateQueries({ queryKey: ["me"] });
  const agree = useMutation({
    mutationFn: () => api.postConsent(NOTICE_VERSION),
    // me is read again, and the app comes back with the agreement.
    onSuccess: readMe,
    // A refused version: me then says which version is current.
    onError: (error) => {
      if (isRefusedVersion(error)) {
        void readMe();
      }
    },
  });
  const signOut = useMutation({
    mutationFn: () => api.signOut(),
    // As on the account screen: me answers 401 and the gate shows.
    onSuccess: () => void queryClient.resetQueries(),
  });
  const refusedVersion = isRefusedVersion(agree.error);
  const outOfDate = props.notice.version !== NOTICE_VERSION || refusedVersion;

  return (
    <>
      <header className="topbar">
        <span className="brand">
          <LogoMark />
          Starvector
        </span>
      </header>
      {/* On each screen of a signed-in device (spec A2 §6.1). */}
      <OperatorCodeNotice />
      <OfflineBanner />
      <main className="page">
        <div className="page-narrow" style={{ margin: "0 auto" }}>
          <section className="card card-hero" aria-labelledby="notice-heading">
            <h1 id="notice-heading" ref={heading} tabIndex={-1}>
              Before you play
            </h1>
            {outOfDate ? (
              <OutOfDate alert={refusedVersion}>
                This page is out of date: the notice about your results has
                changed. Reload it to read the new one.
              </OutOfDate>
            ) : (
              <>
                <NoticeText />
                <p className="muted">
                  This is a condition of playing. To go on, agree to it.
                </p>
              </>
            )}
            {draftKept ? (
              <p className="muted small">
                Your unsent sketch and words are still saved on this device.
              </p>
            ) : null}
            <div className="row">
              {outOfDate ? null : (
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={agree.isPending}
                  onClick={() => agree.mutate()}
                >
                  {agree.isPending ? "Saving…" : "I agree"}
                </button>
              )}
              <button
                type="button"
                className="btn btn-ghost"
                disabled={signOut.isPending}
                onClick={() => signOut.mutate()}
              >
                Sign out
              </button>
            </div>
            {agree.isError && !refusedVersion ? (
              <div className="notice notice-bad" role="alert">
                {friendlyMessage(agree.error)}
              </div>
            ) : null}
            {signOut.isError ? (
              <div className="notice notice-bad" role="alert">
                {friendlyMessage(signOut.error)}
              </div>
            ) : null}
          </section>
        </div>
      </main>
    </>
  );
}
