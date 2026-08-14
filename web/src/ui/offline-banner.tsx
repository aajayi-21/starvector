/**
 * Explicit offline state (spec W1 §8): the shell keeps working, the
 * banner says the network is gone, and scoring paths refuse loudly
 * on their own.
 */

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
    <div
      role="status"
      style={{
        padding: "6px 16px",
        background: "var(--color-neutral-900)",
        color: "var(--color-neutral-300)",
        fontSize: 12,
        textAlign: "center",
      }}
    >
      Offline — the page works, but sending and scoring need the network.
    </div>
  );
}
