/**
 * Makes the image of one share card, and gives it to the device: the
 * share sheet where the browser can share a file, a download where it
 * cannot. The card of a result is a PNG. The card of a sketch, which a
 * player shares before the reveal, is a JPEG (spec SS1 §6).
 */

import type { ShareCard, SketchCard } from "./card";
import { CARD_HEIGHT, CARD_WIDTH } from "./card";
import type { CardContext, CardStroke } from "./draw";
import { drawShareCard, drawSketchCard } from "./draw";

export type ShareOutcome = "shared" | "saved" | "cancelled";

/** The quality of the JPEG of a sketch: thin lines on a flat ground. */
export const JPEG_QUALITY = 0.92;

type ImageEncoding =
  | { type: "image/png" }
  | { type: "image/jpeg"; quality: number };

/**
 * One card as an image file. The image is made on this device, in a
 * canvas that is not on the page, and nothing goes to a server.
 */
async function renderImage(
  draw: (context: CardContext) => void,
  encoding: ImageEncoding,
): Promise<Blob> {
  // The text is drawn with the app's font. A draw before the font is
  // ready falls to the system font, which moves each line.
  try {
    await document.fonts?.ready;
  } catch {
    // A browser with no font set draws with its own font.
  }
  const canvas = document.createElement("canvas");
  canvas.width = CARD_WIDTH;
  canvas.height = CARD_HEIGHT;
  const context = canvas.getContext("2d");
  if (context === null) {
    throw new Error("this browser gives no 2D canvas");
  }
  draw(context);
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob === null) {
          reject(new Error("the browser made no image"));
        } else if (blob.type !== encoding.type) {
          // A browser that cannot write the format gives a PNG: the
          // file would not be what its name says.
          reject(new Error(`the browser made no ${encoding.type} image`));
        } else {
          resolve(blob);
        }
      },
      encoding.type,
      encoding.type === "image/jpeg" ? encoding.quality : undefined,
    );
  });
}

/** The card of a result as a PNG. */
export function renderShareImage(
  card: ShareCard,
  strokes: ReadonlyArray<CardStroke>,
): Promise<Blob> {
  return renderImage((context) => drawShareCard(context, card, strokes), {
    type: "image/png",
  });
}

/** The card of a sketch as a JPEG (spec SS1 §6). */
export function renderSketchImage(
  card: SketchCard,
  strokes: ReadonlyArray<CardStroke>,
): Promise<Blob> {
  return renderImage((context) => drawSketchCard(context, card, strokes), {
    type: "image/jpeg",
    quality: JPEG_QUALITY,
  });
}

function download(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.rel = "noopener";
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // The download starts from the click. The address goes after it.
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

/**
 * Give the image to the device. A browser that can share a file opens
 * its share sheet. Each other browser saves the file. A player who
 * closes the share sheet gets "cancelled", and nothing is saved.
 */
export async function deliverShareImage(
  blob: Blob,
  card: Pick<ShareCard, "fileName" | "shareText">,
): Promise<ShareOutcome> {
  // The file has the type of the image: a PNG for a blob with no type.
  const file = new File([blob], card.fileName, {
    type: blob.type || "image/png",
  });
  const data: ShareData = { files: [file], text: card.shareText };
  if (
    typeof navigator.share === "function" &&
    typeof navigator.canShare === "function" &&
    navigator.canShare(data)
  ) {
    try {
      await navigator.share(data);
      return "shared";
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return "cancelled";
      }
      // A share sheet that does not open is not the end: save the file.
    }
  }
  download(blob, card.fileName);
  return "saved";
}
