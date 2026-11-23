/**
 * The podium of a day's board (owner design of 2026-11-22): the first
 * three players stand as their own sketches, drawn as constellations,
 * on three steps of light. The first stands in the middle and highest,
 * the second at the left, and the third at the right. A faint dashed
 * line joins the three stars, as the lines of a constellation do.
 *
 * Each place says what the table says: the order, the player, the
 * share of the photos beaten, and the place of the photo. No medal, no
 * color for a place, and no word that grades a result (spec M1 §9):
 * the steps are the order and nothing more.
 *
 * The sketch is the sketch alone, never the words (spec SS1 §5). A send
 * with no sketch, or a sketch the operator withheld, says so in its
 * place.
 */

import { useLayoutEffect, useMemo, useRef, useState } from "react";

import type { SendEntry, SendState } from "../api/types";
import type { PlacedRow } from "../board/podium";
import { figureOf } from "../sky/core";
import { AvatarCircle } from "./avatar";
import { ordinal, percentBeaten } from "./format";
import { useNarrow } from "./narrow";
import { SketchFigure } from "./sketch-figure";
import { StreakName } from "./streak-name";

/** The column of each place: the first in the middle. */
const COLUMN = [2, 1, 3] as const;

/** What a place says when its send holds no sketch to draw. */
const MARK: Record<Exclude<SendState, "sketch">, string> = {
  "words-only": "Words only",
  withheld: "Withheld",
  "after-reveal": "Shows after the reveal",
};

export interface PodiumPlace extends PlacedRow {
  /** The send of the player; undefined while the sends still load. */
  send: SendEntry | undefined;
}

function PlaceSketch(props: {
  send: SendEntry | undefined;
}): React.JSX.Element | null {
  const { send } = props;
  const figure = useMemo(
    () =>
      send === undefined || send.state !== "sketch"
        ? null
        : figureOf(send.strokes),
    [send],
  );
  if (send === undefined) {
    // The place keeps its size while the sends load.
    return null;
  }
  if (send.state !== "sketch") {
    return <span className="podium-mark">{MARK[send.state]}</span>;
  }
  return figure === null ? null : (
    <SketchFigure figure={figure} className="podium-sketch" />
  );
}

/**
 * The points of the line through the stars, in the box of the stage,
 * from the left to the right. The stars sit at three heights that the
 * layout sets, so the line reads them from the page.
 */
function useStarLine(
  stage: React.RefObject<HTMLDivElement | null>,
  count: number,
): string {
  const [points, setPoints] = useState("");
  useLayoutEffect(() => {
    const box = stage.current;
    if (box === null || count < 2) {
      setPoints("");
      return;
    }
    const measure = (): void => {
      const base = box.getBoundingClientRect();
      const centers = [...box.querySelectorAll(".podium-star")]
        .map((star) => {
          const at = star.getBoundingClientRect();
          return [
            at.left + at.width / 2 - base.left,
            at.top + at.height / 2 - base.top,
          ] as const;
        })
        .sort((a, b) => a[0] - b[0]);
      setPoints(
        centers.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" "),
      );
    };
    measure();
    if (typeof ResizeObserver !== "function") {
      return;
    }
    // A new width, a font that arrives, or a sketch that loads moves
    // the stars: the line follows.
    const watch = new ResizeObserver(measure);
    watch.observe(box);
    for (const place of box.querySelectorAll(".podium-place")) {
      watch.observe(place);
    }
    return () => watch.disconnect();
  }, [stage, count]);
  return points;
}

export function Podium(props: {
  places: ReadonlyArray<PodiumPlace>;
  self: string;
}): React.JSX.Element {
  const stage = useRef<HTMLDivElement | null>(null);
  const line = useStarLine(stage, props.places.length);
  const narrow = useNarrow();
  return (
    <div className="podium" ref={stage}>
      {line === "" ? null : (
        <svg className="podium-line" aria-hidden="true">
          <polyline points={line} />
        </svg>
      )}
      <ol className="podium-places" aria-label="The first three">
        {props.places.map((place, index) => {
          const { row, order, tied } = place;
          const step = Math.min(order ?? 3, 3);
          const mine = row.player === props.self;
          return (
            <li
              key={row.player}
              className={mine ? "podium-place is-you" : "podium-place"}
              data-step={step}
              data-player={row.player}
              style={{ gridColumn: COLUMN[index] }}
            >
              <span className="podium-figure">
                <PlaceSketch send={place.send} />
              </span>
              <span className="podium-star" aria-hidden="true" />
              <span className="podium-order">
                {order === null ? "" : ordinal(order)}
                {tied ? ", tied" : ""}
              </span>
              <span className="podium-who">
                <AvatarCircle
                  player={row.player}
                  avatarHash={row.avatar_hash}
                  size={narrow ? 30 : 40}
                  streak={row.streak}
                />
                <span className="player-name">
                  <StreakName streak={row.streak}>
                    {mine ? "You" : row.player}
                  </StreakName>
                </span>
              </span>
              <span className="podium-result">{percentBeaten(row.p)}%</span>
              <span className="podium-photo">
                {ordinal(row.target_rank)} of {row.decoy_count + 1} photos
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
