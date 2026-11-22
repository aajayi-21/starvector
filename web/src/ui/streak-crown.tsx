/**
 * The streak as a crown over the day's code (the home screen): an arc
 * of stars, one for each day in a row, with today's place at its end.
 * The arc fills as the streak grows, and the words under it say the
 * streak.
 *
 * A star is a revealed day: a larger star is a better result, and a
 * press opens that day. Today's place is a ring: it waits until the
 * send, fills when the sketch is in, and is gone when the day is
 * revealed, because that day is then a star of the streak. The ring
 * says only whether the player sent (I7). The crown draws what the
 * history holds and judges nothing (I2).
 *
 * sky/home.ts holds the geometry. The crown measures nothing: each
 * place is a share of its width, so it needs no layout pass.
 */

import { Link } from "@tanstack/react-router";

import type { Figure } from "../sky/core";
import {
  type CrownDay,
  type CrownPlace,
  crownPlace,
  crownPlaces,
  crownStarRadius,
} from "../sky/home";
import { useDayNames } from "./day-names";
import { percentBeaten } from "./format";
import { SketchFigure } from "./sketch-figure";
import { streakLabel } from "./streak";

/**
 * Today's place on the crown: waiting for a send, sent, or closed with
 * no send. Null when the newest day is revealed.
 */
export type CrownToday = "waiting" | "sent" | "missed" | null;

const TODAY_WORDS: Record<Exclude<CrownToday, null>, string> = {
  waiting: "Today: not sent yet",
  sent: "Today: your sketch is in",
  missed: "Today: not sent",
};

/** How many points draw the dotted arc. */
const TRACK_STEPS = 40;

function pointsOf(places: ReadonlyArray<CrownPlace>): string {
  return places
    .map(
      (place) => `${(place.x * 100).toFixed(2)},${(place.y * 100).toFixed(2)}`,
    )
    .join(" ");
}

function placeStyle(place: CrownPlace, radius?: number): React.CSSProperties {
  return {
    "--crown-x": place.x.toFixed(4),
    "--crown-y": place.y.toFixed(4),
    ...(radius === undefined ? {} : { "--crown-r": `${radius.toFixed(2)}px` }),
  } as React.CSSProperties;
}

/** The side a day's words open to, so they stay inside the window. */
function tipSide(place: CrownPlace): string {
  if (place.x < 0.3) {
    return "crown-tip is-left";
  }
  return place.x > 0.7 ? "crown-tip is-right" : "crown-tip";
}

export function StreakCrown(props: {
  /** The streak in days, as the server counts it. */
  streak: number;
  /** The days of the streak that the crown draws, the oldest first. */
  days: ReadonlyArray<CrownDay>;
  /** The sketch of a day as a constellation, when it is loaded. */
  figureOf: (day: string) => Figure | null;
  today: CrownToday;
}): React.JSX.Element {
  const names = useDayNames();
  const { days, today } = props;
  const places = crownPlaces(days.length + (today === null ? 0 : 1));
  const dayPlaces = places.slice(0, days.length);
  const todayPlace = today === null ? undefined : places[places.length - 1];
  const lastDay = dayPlaces[dayPlaces.length - 1];
  const track = Array.from({ length: TRACK_STEPS + 1 }, (_, index) =>
    crownPlace(index / TRACK_STEPS),
  );
  // A sent day joins the line of the streak; a day that waits does not.
  const joined =
    today === "sent" && todayPlace !== undefined
      ? [...dayPlaces, todayPlace]
      : dayPlaces;

  return (
    // biome-ignore lint/a11y/useSemanticElements: a fieldset draws a box, and nothing here has one.
    <div className="crown" role="group" aria-label="Your streak">
      <svg
        className="crown-lines"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <polyline className="crown-track" points={pointsOf(track)} />
        {joined.length > 1 ? (
          <polyline className="crown-thread" points={pointsOf(joined)} />
        ) : null}
        {today !== "sent" &&
        todayPlace !== undefined &&
        lastDay !== undefined ? (
          <polyline
            className="crown-thread is-pending"
            points={pointsOf([lastDay, todayPlace])}
          />
        ) : null}
      </svg>
      {days.map((each, index) => {
        const place = dayPlaces[index];
        if (place === undefined) {
          return null;
        }
        const style = placeStyle(place, crownStarRadius(each.p));
        const date = names.long(each.day);
        if (each.p === null) {
          return (
            <span
              key={each.day}
              className="crown-star"
              style={style}
              role="img"
              aria-label={`${date}: sent, with no result`}
            >
              <span className="crown-dot" />
            </span>
          );
        }
        const figure = props.figureOf(each.day);
        const percent = percentBeaten(each.p);
        return (
          <Link
            key={each.day}
            to="/reveal"
            search={{ day: each.day }}
            className="crown-star"
            style={style}
            aria-label={`${date}: you beat ${percent}% of the photos`}
          >
            <span className="crown-dot" />
            <span className={tipSide(place)} aria-hidden="true">
              {figure === null ? null : (
                <SketchFigure figure={figure} className="crown-tip-sketch" />
              )}
              <span className="crown-tip-words">
                <span className="crown-tip-date">{date}</span>
                <span>
                  You beat <strong>{percent}%</strong> of the photos
                </span>
              </span>
            </span>
          </Link>
        );
      })}
      {today === null || todayPlace === undefined ? null : (
        <span
          className={`crown-today is-${today}`}
          style={placeStyle(todayPlace)}
          role="img"
          aria-label={TODAY_WORDS[today]}
        />
      )}
      <p className="crown-label" data-testid="streak-label">
        {props.streak === 0 ? "No streak yet" : streakLabel(props.streak)}
      </p>
    </div>
  );
}
