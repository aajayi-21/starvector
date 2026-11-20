/**
 * Explicit offline state (spec W1 §8): the shell keeps working, the
 * banner says the network is gone, and scoring paths refuse loudly
 * on their own.
 */

import { WifiSlash } from "@phosphor-icons/react";
import { useSyncExternalStore } from "react";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("online", onChange);
  window.addEventListener("offline", onChange);
  return () => {
    window.removeEventListener("online", onChange);
    window.removeEventListener("offline", onChange);
  };
}

const isOnline = (): boolean => navigator.onLine;

export function OfflineBanner(): React.JSX.Element | null {
  const online = useSyncExternalStore(subscribe, isOnline, () => true);
  if (online) {
    return null;
  }
  return (
    <div role="status" className="shell-note">
      <WifiSlash size={18} aria-hidden="true" />
      <span>
        You're offline. You can keep sketching, but sending needs a connection.
      </span>
    </div>
  );
}
