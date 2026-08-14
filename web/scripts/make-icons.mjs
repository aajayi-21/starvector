/**
 * One-time icon rasterization (spec W1 B10): renders the vendored
 * appicon SVG into the PWA PNG set. Outputs are committed, so
 * builds and CI never run this — re-run `pnpm icons` only when the
 * brand SVG changes, and review the diff.
 */

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { Resvg } from "@resvg/resvg-js";

const here = dirname(fileURLToPath(import.meta.url));
const appicon = readFileSync(
  join(here, "../src/brand/starvector-appicon.svg"),
  "utf8",
);
// The maskable variant fills the full square: the platform mask
// crops its own shape, and the mark already sits in the safe zone.
const maskable = appicon.replace('rx="22"', 'rx="0"');

const outDir = join(here, "../public/icons");
mkdirSync(outDir, { recursive: true });

const render = (svg, size) =>
  new Resvg(svg, { fitTo: { mode: "width", value: size } }).render().asPng();

for (const [name, svg, size] of [
  ["appicon-192.png", appicon, 192],
  ["appicon-512.png", appicon, 512],
  ["appicon-maskable-512.png", maskable, 512],
  ["apple-touch-icon.png", appicon, 180],
]) {
  writeFileSync(join(outDir, name), render(svg, size));
  console.log(`wrote icons/${name}`);
}
