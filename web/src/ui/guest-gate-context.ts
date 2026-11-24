/**
 * The way from guest play to the gate screen (spec IM1 §16). The shell
 * of a guest gives it, and a screen inside the shell opens the gate
 * with it. An account has none: the hook then gives null.
 */

import { createContext, useContext } from "react";

export interface GuestGate {
  /** Shows the gate screen, where the guest makes an account. */
  openGate: () => void;
}

export const GuestGateContext = createContext<GuestGate | null>(null);

export function useGuestGate(): GuestGate | null {
  return useContext(GuestGateContext);
}
