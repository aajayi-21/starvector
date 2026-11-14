/**
 * The two pieces that each screen with the notice shares (spec R1
 * §3.1): the notice text, and the line that says this page is out of
 * date. The text and its version number come from `notice.ts`, the one
 * module that holds them.
 */

import { NOTICE_BODY, NOTICE_LEAD } from "./notice";

/** The notice that results are public, as one paragraph. */
export function NoticeText(): React.JSX.Element {
  return (
    <p>
      <strong>{NOTICE_LEAD}</strong> {NOTICE_BODY}
    </p>
  );
}

/**
 * This page holds a notice version that is not the server's current
 * one, thus it cannot show the text a player must agree to. A reload
 * gets the current page. The control is here because a home-screen app
 * has no reload button of its own.
 */
export function OutOfDate(props: {
  /** True when the line shows after a click, and not with the page. */
  alert?: boolean;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <div
      className="notice notice-warn"
      role={props.alert === true ? "alert" : "note"}
    >
      <div className="stack-sm">
        <span>{props.children}</span>
        <div>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => window.location.reload()}
          >
            Reload
          </button>
        </div>
      </div>
    </div>
  );
}
