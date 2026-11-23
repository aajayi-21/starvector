/**
 * The day's board of the leaderboard (screens/leaderboard.tsx), as the
 * owner's design of 2026-11-22 lays it out: the photo of the day at the
 * left and the podium of the first three beside it, then the river of
 * the day's sketches, then the rest of the board as a plain table
 * (spec M1 §9).
 *
 * The board shows revealed days alone, so the photo and each sketch
 * here belong to a day that is over (I7, spec SS1 §4). The code of the
 * day stands once, in the line under the title, and not again by the
 * photo.
 */

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";

import { useApi } from "../api/client";
import type { LeaderboardRow, LeaderboardView, SendEntry } from "../api/types";
import { friendlyMessage } from "../api/types";
import { floorSentence, privateOwnRow } from "../board/core";
import {
  type PlacedRow,
  placeRows,
  podiumRows,
  sendsByPlayer,
} from "../board/podium";
import { figureOf } from "../sky/core";
import { AvatarCircle } from "../ui/avatar";
import { useDayNames } from "../ui/day-names";
import { ordinal, percentBeaten } from "../ui/format";
import { Podium } from "../ui/podium";
import { PrivateRowBadge } from "../ui/private-row-badge";
import { SketchFigure } from "../ui/sketch-figure";
import { type RiverSketch, SketchRiver } from "../ui/sketch-river";
import { StreakName } from "../ui/streak-name";
import { Credit } from "./reveal";

export function DayBoard(props: {
  view: LeaderboardView;
  self: string;
}): React.JSX.Element {
  const { view, self } = props;
  const sends = useDaySends(view.day);
  const placed = placeRows(view.rows);
  const podium = podiumRows(placed);
  const rest = placed.filter((one) => !podium.includes(one));
  return (
    <div className="board-day">
      <div className="board-lead">
        <DayPhoto day={view.day} />
        {podium.length === 0 ? (
          <p className="muted board-empty">No results this day.</p>
        ) : (
          <Podium
            places={podium.map((one) => ({
              ...one,
              send: sends.byPlayer.get(one.row.player),
            }))}
            self={self}
          />
        )}
      </div>
      <SketchRiver sketches={riverSketches(sends.all, view.rows, self)} />
      {sends.error === null ? null : (
        <p className="hint" role="alert">
          The sketches of this day didn't load. {friendlyMessage(sends.error)}
        </p>
      )}
      <BoardTable
        view={view}
        rest={rest}
        self={self}
        byPlayer={sends.byPlayer}
      />
    </div>
  );
}

/**
 * Each send of the day. The podium and the table want the sketch of
 * each player, and the sends come a page at a time, the newest first
 * (spec SS1 §7.2), so this reads each page in turn. The key and the
 * request are those of the sends screen: one read serves both.
 */
function useDaySends(day: string): {
  all: SendEntry[];
  byPlayer: Map<string, SendEntry>;
  error: unknown;
} {
  const api = useApi();
  const sends = useInfiniteQuery({
    queryKey: ["day-sends", day],
    queryFn: ({ pageParam }) => api.getSends(day, pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => last.next_before ?? undefined,
    retry: false,
  });
  const { hasNextPage, isFetchingNextPage, isError, fetchNextPage } = sends;
  const pages = sends.data?.pages;
  // The count of pages is in the list: a fast answer can start and end
  // a read in one render, and the other values then look unchanged.
  const pageCount = pages?.length ?? 0;
  useEffect(() => {
    if (pageCount > 0 && hasNextPage && !isFetchingNextPage && !isError) {
      void fetchNextPage();
    }
  }, [pageCount, hasNextPage, isFetchingNextPage, isError, fetchNextPage]);
  return useMemo(
    () => ({
      all: (pages ?? []).flatMap((page) => page.entries),
      byPlayer: sendsByPlayer(pages ?? []),
      error: isError ? sends.error : null,
    }),
    [pages, isError, sends.error],
  );
}

/**
 * The sketches of the river, in the sequence of the sends. A name gets
 * its result only where the board shows a row for it: the sends hold
 * each player, and the board hides a row below its floor (spec A2
 * §9.5), so the river must not show that result.
 */
function riverSketches(
  sends: ReadonlyArray<SendEntry>,
  rows: ReadonlyArray<LeaderboardRow>,
  self: string,
): RiverSketch[] {
  const results = new Map(rows.map((row) => [row.player, row.p]));
  const sketches: RiverSketch[] = [];
  for (const send of sends) {
    const figure = send.state === "sketch" ? figureOf(send.strokes) : null;
    if (figure === null) {
      continue;
    }
    const name = send.named && send.player === self ? "You" : send.player;
    const p = results.get(send.player);
    sketches.push({
      key: send.player,
      figure,
      label: p === undefined ? name : `${name} · ${percentBeaten(p)}%`,
    });
  }
  return sketches;
}

/** The photo of the day, square, with its name and its credit. */
function DayPhoto(props: { day: string }): React.JSX.Element {
  const api = useApi();
  const names = useDayNames();
  // The key and the request of the Results screen for a named day.
  const reveal = useQuery({
    queryKey: ["reveal", props.day],
    queryFn: () => api.getReveal(props.day),
  });
  const name = `The photo of ${names.long(props.day)}`;
  return (
    <figure className="board-photo">
      <div className="picture-frame">
        {reveal.data === undefined ? null : (
          <img
            src={api.imageUrl(reveal.data.target_id)}
            alt={reveal.data.credit?.title ?? name}
          />
        )}
      </div>
      <figcaption>
        <span className="board-photo-name">{name}</span>
        {reveal.data !== undefined ? (
          <Credit credit={reveal.data.credit} />
        ) : reveal.isError ? (
          <span className="hint" role="alert">
            The photo didn't load. {friendlyMessage(reveal.error)}
          </span>
        ) : null}
      </figcaption>
    </figure>
  );
}

/** A sketch in a row of the table: the sketch alone, small. */
function RowSketch(props: {
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
  return figure === null ? null : (
    <SketchFigure figure={figure} className="board-row-sketch" />
  );
}

/** The rows after the podium: a plain table, as spec M1 §9 asks. */
function BoardTable(props: {
  view: LeaderboardView;
  rest: ReadonlyArray<PlacedRow>;
  self: string;
  byPlayer: ReadonlyMap<string, SendEntry>;
}): React.JSX.Element {
  const { view, rest, self } = props;
  // The caller's own row while it is below the floor of spec A2 §9.5.
  const hidden = privateOwnRow(view.rows, self);
  // The photos of one day are one set, so the count stands one time
  // under the table. Rows that disagree keep their own count.
  const totals = new Set(view.rows.map((row) => row.decoy_count + 1));
  const [total] = totals;
  const shared = totals.size === 1 && total !== undefined ? total : null;
  return (
    <section className="board-rest" aria-label="The rest of the board">
      {rest.length === 0 ? null : (
        <div className="table-scroll">
          <table className="table board-day-table">
            <thead>
              <tr>
                <th scope="col" className="num">
                  <span className="visually-hidden">Order</span>
                </th>
                <th scope="col">Player</th>
                <th scope="col" className="board-hide-narrow">
                  <span className="visually-hidden">Sketch</span>
                </th>
                <th scope="col" className="num">
                  Result
                </th>
                <th scope="col" className="num">
                  Place
                </th>
                <th scope="col" className="num">
                  Streak
                </th>
              </tr>
            </thead>
            <tbody>
              {rest.map(({ row, order, tied }) => (
                <tr
                  key={row.player}
                  className={row.player === self ? "is-you" : undefined}
                  data-player={row.player}
                >
                  <td className="num board-order">
                    {order === null ? "" : order}
                    {tied ? (
                      <span className="visually-hidden">, tied</span>
                    ) : null}
                  </td>
                  <td>
                    <span className="board-player">
                      <AvatarCircle
                        player={row.player}
                        avatarHash={row.avatar_hash}
                        size={28}
                        streak={row.streak}
                      />
                      <span
                        className="player-name"
                        title={row.player === self ? undefined : row.player}
                      >
                        <StreakName streak={row.streak}>
                          {row.player === self ? "You" : row.player}
                        </StreakName>
                      </span>
                    </span>
                    {row === hidden ? <PrivateRowBadge /> : null}
                  </td>
                  <td className="board-sketch-cell board-hide-narrow">
                    <RowSketch send={props.byPlayer.get(row.player)} />
                  </td>
                  <td className="num">{percentBeaten(row.p)}%</td>
                  <td className="num muted">
                    {shared === null
                      ? `${ordinal(row.target_rank)} of ${row.decoy_count + 1}`
                      : ordinal(row.target_rank)}
                  </td>
                  <td className="num muted">{row.streak}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="subtle tiny">
        Result is the share of the photos that each player beat. Guessing
        averages 50%.
        {shared === null ? null : ` Place is out of ${shared} photos.`}
      </p>
      {hidden === null ? null : (
        <p className="hint" data-testid="board-floor">
          {floorSentence(view.floor)}
        </p>
      )}
    </section>
  );
}
