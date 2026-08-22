/**
 * The client-side avatar downscale (spec A1, D2): the picked image
 * shrinks to 256 px on its longest side on a canvas before the
 * PUT, so a phone photograph lands well below the 1 MiB wire cap.
 * The output is always PNG — one of the four kinds the server
 * accepts by magic bytes.
 */

export const AVATAR_MAX_PX = 256;

/** The target box: the longest side capped, the ratio kept. */
export function scaledBox(
  width: number,
  height: number,
  maxPx: number = AVATAR_MAX_PX,
): { width: number; height: number } {
  const longest = Math.max(width, height);
  if (longest <= maxPx) {
    return { width, height };
  }
  const factor = maxPx / longest;
  return {
    width: Math.max(1, Math.round(width * factor)),
    height: Math.max(1, Math.round(height * factor)),
  };
}

export async function downscaleImage(
  file: Blob,
  maxPx: number = AVATAR_MAX_PX,
): Promise<Blob> {
  const bitmap = await createImageBitmap(file);
  try {
    const box = scaledBox(bitmap.width, bitmap.height, maxPx);
    const canvas = document.createElement("canvas");
    canvas.width = box.width;
    canvas.height = box.height;
    const context = canvas.getContext("2d");
    if (context === null) {
      throw new Error("no 2d canvas context");
    }
    context.drawImage(bitmap, 0, 0, box.width, box.height);
    return await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((blob) => {
        if (blob === null) {
          reject(new Error("the canvas gave no image"));
        } else {
          resolve(blob);
        }
      }, "image/png");
    });
  } finally {
    bitmap.close();
  }
}
