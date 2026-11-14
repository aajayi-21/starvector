/**
 * The recovery-code step (spec A2 §3.1 step 4, §6): the one time a
 * recovery code is on screen. The player copies it and then clicks
 * `I have my code`. Nothing else continues the flow, thus a player
 * cannot pass the code without a deliberate click.
 *
 * The code is held in component state alone. It does not go to
 * localStorage, to a URL, or to the query cache.
 */

import { Copy } from "@phosphor-icons/react";
import { useEffect, useId, useRef, useState } from "react";

export function RecoveryCodeStep(props: {
  /** Six groups of four, as the server shows it. */
  code: string;
  /** What the earlier code is now, when there was one. */
  replaces?: boolean;
  onDone: () => void;
}): React.JSX.Element {
  const { code, onDone } = props;
  const [copied, setCopied] = useState<"no" | "yes" | "failed">("no");
  const heading = useRef<HTMLHeadingElement>(null);
  // Two steps can be on one screen (the account screen), thus the
  // heading id is not a constant.
  const headingId = useId();

  // The step replaces a form: focus moves to it, thus a screen reader
  // announces the step and the keyboard starts at its heading.
  useEffect(() => {
    heading.current?.focus();
  }, []);

  const copy = () => {
    const clipboard = navigator.clipboard;
    if (clipboard === undefined) {
      setCopied("failed");
      return;
    }
    clipboard
      .writeText(code)
      .then(() => setCopied("yes"))
      .catch(() => setCopied("failed"));
  };

  return (
    <section className="recovery-step" aria-labelledby={headingId}>
      <h2 id={headingId} ref={heading} tabIndex={-1}>
        Save your recovery code
      </h2>
      <p>
        This code is the only way back into your account if you lose your
        password. <strong>It will not be shown again.</strong>
      </p>
      <div className="recovery-code" data-testid="recovery-code">
        {code.split("-").map((group, index) => (
          // The code is positional; the index is the identity.
          // biome-ignore lint/suspicious/noArrayIndexKey: positional groups
          <span key={index}>{group}</span>
        ))}
      </div>
      <div className="row">
        <button type="button" className="btn btn-secondary" onClick={copy}>
          <Copy size={18} aria-hidden="true" />
          Copy the code
        </button>
        <span className="subtle small" aria-live="polite">
          {copied === "yes"
            ? "Copied."
            : copied === "failed"
              ? "Couldn't copy. Select the code and copy it by hand."
              : ""}
        </span>
      </div>
      <p className="muted small">
        Keep it somewhere only you can read, like a password manager. It works
        one time: when you use it, you get a new one.
        {props.replaces === true
          ? " Any recovery code you had before has stopped working."
          : ""}
      </p>
      <div>
        <button type="button" className="btn btn-primary" onClick={onDone}>
          I have my code
        </button>
      </div>
    </section>
  );
}
