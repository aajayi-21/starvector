/**
 * Give an address to the device (spec IM1 §16): the share sheet of the
 * browser where it has one, and the clipboard in each other browser.
 * A player who closes the share sheet gets "cancelled".
 */

export type AddressOutcome = "shared" | "copied" | "cancelled" | "failed";

export async function shareAddress(
  address: string,
  text: string,
): Promise<AddressOutcome> {
  const data: ShareData = { url: address, text };
  if (typeof navigator.share === "function") {
    try {
      await navigator.share(data);
      return "shared";
    } catch (error) {
      // The player closed the sheet: nothing is copied behind it.
      if (error instanceof DOMException && error.name === "AbortError") {
        return "cancelled";
      }
    }
  }
  try {
    await navigator.clipboard.writeText(address);
    return "copied";
  } catch {
    return "failed";
  }
}

/** The address of the public page of one instant trial. */
export function trialAddress(date: string, trialId: string): string {
  return `${window.location.origin}/t/${date}/${trialId}`;
}
