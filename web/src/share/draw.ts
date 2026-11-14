/**
 * Draws one share card on a 2D context: the brand, the day, the big
 * percent, the bar against the 50% guessing mark, the player's own
 * sketch, and the place of the hidden photo.
 *
 * The function draws with a small set of context calls and reads no
 * global, so a unit test gives it a recording context. The card has
 * its own dark palette: an image that leaves the app does not follow
 * the reader's theme.
 */

import type { ShareCard } from "./card";
import { CARD_HEIGHT, CARD_WIDTH } from "./card";

export interface CardStroke {
  points: ReadonlyArray<readonly [number, number]>;
  color?: string | undefined;
}

/** The context calls that the card uses. */
export type CardContext = Pick<
  CanvasRenderingContext2D,
  | "fillStyle"
  | "strokeStyle"
  | "lineWidth"
  | "lineCap"
  | "lineJoin"
  | "font"
  | "textAlign"
  | "textBaseline"
  | "beginPath"
  | "closePath"
  | "moveTo"
  | "lineTo"
  | "arc"
  | "arcTo"
  | "bezierCurveTo"
  | "fill"
  | "stroke"
  | "fillRect"
  | "fillText"
  | "measureText"
  | "save"
  | "restore"
  | "clip"
>;

const COLOR = {
  ground: "#0e1116",
  panel: "#161b23",
  border: "#29303c",
  text: "#e7eaf0",
  muted: "#b3bccb",
  quiet: "#949eaf",
  accent: "#7ba3ff",
  track: "#1e2530",
  canvas: "#1f2430",
  canvasBorder: "#353d4d",
  ink: "#eceff4",
} as const;

const FONT = '"Inter", system-ui, -apple-system, "Segoe UI", sans-serif';
const MONO = 'ui-monospace, "SF Mono", Menlo, Consolas, monospace';
const MARGIN = 72;
const SKETCH_SIDE = 420;

function font(weight: number, size: number, family: string = FONT): string {
  return `${weight} ${size}px ${family}`;
}

function roundedRect(
  context: CardContext,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
): void {
  const r = Math.min(radius, width / 2, height / 2);
  context.beginPath();
  context.moveTo(x + r, y);
  context.arcTo(x + width, y, x + width, y + height, r);
  context.arcTo(x + width, y + height, x, y + height, r);
  context.arcTo(x, y + height, x, y, r);
  context.arcTo(x, y, x + width, y, r);
  context.closePath();
}

/** The five-ray mark of the nav bar, in a box of the given side. */
function drawMark(
  context: CardContext,
  x: number,
  y: number,
  side: number,
): void {
  const unit = side / 96;
  const at = (value: number, origin: number): number => origin + value * unit;
  context.strokeStyle = COLOR.accent;
  context.lineWidth = 6 * unit;
  context.lineCap = "round";
  context.lineJoin = "round";
  context.beginPath();
  context.arc(at(48, x), at(34, y), 16 * unit, 0, Math.PI * 2);
  context.stroke();
  const rays: ReadonlyArray<readonly [number, number, number, number]> = [
    [48, 12, 48, 4],
    [70, 34, 78, 34],
    [26, 34, 18, 34],
    [63, 19, 69, 13],
    [33, 19, 27, 13],
  ];
  for (const [x1, y1, x2, y2] of rays) {
    context.beginPath();
    context.moveTo(at(x1, x), at(y1, y));
    context.lineTo(at(x2, x), at(y2, y));
    context.stroke();
  }
  context.beginPath();
  context.moveTo(at(48, x), at(50, y));
  context.bezierCurveTo(
    at(45, x),
    at(60, y),
    at(52, x),
    at(64, y),
    at(48, x),
    at(72, y),
  );
  context.bezierCurveTo(
    at(45, x),
    at(79, y),
    at(36, x),
    at(82, y),
    at(30, x),
    at(78, y),
  );
  context.stroke();
}

function drawMeter(
  context: CardContext,
  card: ShareCard,
  x: number,
  y: number,
  width: number,
): void {
  const height = 28;
  context.fillStyle = COLOR.track;
  roundedRect(context, x, y, width, height, height / 2);
  context.fill();
  if (card.percent > 0) {
    context.save();
    roundedRect(context, x, y, width, height, height / 2);
    context.clip();
    context.fillStyle = COLOR.accent;
    context.fillRect(x, y, (width * card.percent) / 100, height);
    context.restore();
  }
  // The mark at 50%: what guessing gets on average.
  context.fillStyle = COLOR.text;
  context.fillRect(x + width / 2 - 2, y - 10, 4, height + 20);
  context.fillStyle = COLOR.quiet;
  context.font = font(500, 28);
  context.textBaseline = "top";
  context.textAlign = "left";
  context.fillText("0%", x, y + height + 22);
  context.textAlign = "center";
  context.fillText(card.chanceLabel, x + width / 2, y + height + 22);
  context.textAlign = "right";
  context.fillText("100%", x + width, y + height + 22);
}

function drawSketch(
  context: CardContext,
  strokes: ReadonlyArray<CardStroke>,
  x: number,
  y: number,
  side: number,
): void {
  context.fillStyle = COLOR.canvas;
  roundedRect(context, x, y, side, side, 24);
  context.fill();
  context.strokeStyle = COLOR.canvasBorder;
  context.lineWidth = 2;
  roundedRect(context, x, y, side, side, 24);
  context.stroke();
  context.save();
  roundedRect(context, x, y, side, side, 24);
  context.clip();
  context.lineWidth = 5;
  context.lineCap = "round";
  context.lineJoin = "round";
  for (const stroke of strokes) {
    if (stroke.points.length === 0) {
      continue;
    }
    context.strokeStyle = stroke.color ?? COLOR.ink;
    context.beginPath();
    stroke.points.forEach(([px, py], index) => {
      const cx = x + px * side;
      const cy = y + py * side;
      if (index === 0) {
        context.moveTo(cx, cy);
      } else {
        context.lineTo(cx, cy);
      }
    });
    if (stroke.points.length === 1) {
      // One point is a dot: a line to itself draws the round cap.
      const [px, py] = stroke.points[0] as readonly [number, number];
      context.lineTo(x + px * side, y + py * side);
    }
    context.stroke();
  }
  context.restore();
}

function drawPlace(
  context: CardContext,
  card: ShareCard,
  x: number,
  centerY: number,
  align: "left" | "center",
): void {
  context.textAlign = align;
  context.textBaseline = "alphabetic";
  context.fillStyle = COLOR.muted;
  context.font = font(500, 34);
  context.fillText(card.placeLead, x, centerY - 78);
  context.fillStyle = COLOR.text;
  context.font = font(800, 120);
  context.fillText(card.placeValue, x, centerY + 40);
  context.fillStyle = COLOR.muted;
  context.font = font(500, 34);
  context.fillText(card.placeTail, x, centerY + 96);
}

/**
 * Draw the card on a context of CARD_WIDTH by CARD_HEIGHT pixels.
 * With no stroke the card has no sketch panel, and the place of the
 * hidden photo sits in the middle.
 */
export function drawShareCard(
  context: CardContext,
  card: ShareCard,
  strokes: ReadonlyArray<CardStroke>,
): void {
  const inner = CARD_WIDTH - 2 * MARGIN;
  context.fillStyle = COLOR.ground;
  context.fillRect(0, 0, CARD_WIDTH, CARD_HEIGHT);
  context.fillStyle = COLOR.panel;
  roundedRect(context, 32, 32, CARD_WIDTH - 64, CARD_HEIGHT - 64, 44);
  context.fill();
  context.strokeStyle = COLOR.border;
  context.lineWidth = 2;
  roundedRect(context, 32, 32, CARD_WIDTH - 64, CARD_HEIGHT - 64, 44);
  context.stroke();

  // The brand and the day.
  drawMark(context, MARGIN, 84, 72);
  context.fillStyle = COLOR.text;
  context.font = font(700, 46);
  context.textAlign = "left";
  context.textBaseline = "middle";
  context.fillText("Starvector", MARGIN + 88, 120);
  context.textAlign = "right";
  context.fillStyle = COLOR.muted;
  context.font = font(500, 34);
  context.fillText(card.dateLine, CARD_WIDTH - MARGIN, 104);
  if (card.codeLine !== null) {
    context.fillStyle = COLOR.quiet;
    context.font = font(600, 28, MONO);
    context.fillText(card.codeLine, CARD_WIDTH - MARGIN, 146);
  }

  // The result against chance.
  context.textAlign = "left";
  context.textBaseline = "alphabetic";
  context.fillStyle = COLOR.text;
  context.font = font(800, 300);
  context.fillText(card.percentText, MARGIN - 8, 500);
  context.fillStyle = COLOR.muted;
  context.font = font(500, 44);
  context.fillText(card.captionLine, MARGIN, 574);
  drawMeter(context, card, MARGIN, 640, inner);

  // The player's own sketch, and the place of the hidden photo.
  const blockTop = 790;
  const blockCenter = blockTop + SKETCH_SIDE / 2;
  const hasSketch = strokes.some((stroke) => stroke.points.length > 0);
  if (hasSketch) {
    drawSketch(context, strokes, MARGIN, blockTop, SKETCH_SIDE);
    drawPlace(context, card, MARGIN + SKETCH_SIDE + 56, blockCenter, "left");
  } else {
    drawPlace(context, card, CARD_WIDTH / 2, blockCenter, "center");
  }

  // Who and where.
  context.textBaseline = "alphabetic";
  context.font = font(600, 30);
  if (card.byLine !== null) {
    context.textAlign = "left";
    context.fillStyle = COLOR.text;
    context.fillText(card.byLine, MARGIN, CARD_HEIGHT - 84);
  }
  context.textAlign = "right";
  context.fillStyle = COLOR.accent;
  context.fillText(card.siteLine, CARD_WIDTH - MARGIN, CARD_HEIGHT - 84);
}
