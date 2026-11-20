/**
 * The install layer (spec W1 B10): Android and desktop get the
 * captured beforeinstallprompt as a button; iOS has no prompt
 * event, so a one-time Share → Add to Home Screen hint shows
 * instead. Dismissal is remembered on the device.
 */

import { X } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

const DISMISSED_KEY = "sv:install-hint-dismissed";

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
}

function dismissed(): boolean {
  try {
    return window.localStorage.getItem(DISMISSED_KEY) !== null;
  } catch {
    return true;
  }
}

function isStandalone(): boolean {
  return (
    window.matchMedia?.("(display-mode: standalone)").matches === true ||
    (navigator as { standalone?: boolean }).standalone === true
  );
}

const isIos = (): boolean => /iPad|iPhone|iPod/.test(navigator.userAgent);

export function InstallHint(): React.JSX.Element | null {
  const [prompt, setPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [hidden, setHidden] = useState(() => dismissed() || isStandalone());

  useEffect(() => {
    const onPrompt = (event: Event) => {
      event.preventDefault();
      setPrompt(event as BeforeInstallPromptEvent);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    return () => window.removeEventListener("beforeinstallprompt", onPrompt);
  }, []);

  if (hidden || (prompt === null && !isIos())) {
    return null;
  }

  const dismiss = () => {
    setHidden(true);
    try {
      window.localStorage.setItem(DISMISSED_KEY, "1");
    } catch {
      // Device-local nicety; a failed write costs nothing.
    }
  };

  return (
    <div className="shell-note">
      {prompt === null ? (
        <span className="shell-note-text">
          Add Starvector to your Home Screen: tap Share, then Add to Home
          Screen. The app opens signed out the first time. Sign in with a device
          code from your Account page.
        </span>
      ) : (
        <>
          <span className="shell-note-text">Install Starvector as an app.</span>
          <button
            type="button"
            className="btn btn-secondary shell-note-button"
            onClick={() => {
              void prompt.prompt();
              dismiss();
            }}
          >
            Install
          </button>
        </>
      )}
      <button
        type="button"
        className="btn btn-icon"
        aria-label="Dismiss"
        onClick={dismiss}
      >
        <X size={18} aria-hidden="true" />
      </button>
    </div>
  );
}
