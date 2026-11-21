/**
 * The sketches of one day (spec SS1 §7.3): what each player sent, as
 * the sketch alone. The send count of the home screen and of the Play
 * screen opens it.
 *
 * Send, then see: the day in play shows its sketches to a player whose
 * own sketch is sent. Before that the screen says so and asks the
 * server for nothing. One send for each day is the rule, so a player
 * who sees these sketches has no sketch to change.
 *
 * The grid is plain on purpose. The owner picks a gallery from mock
 * screens, and that gallery can replace it.
 */

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Link, useSearch } from "@tanstack/react-router";

import { useApi } from "../api/client";
import { useDayQuery } from "../api/day-query";
import type { DayView, SendEntry, SendState } from "../api/types";
import { friendlyMessage, isRefusal } from "../api/types";
import { AvatarCircle } from "../ui/avatar";
import { useDayNames } from "../ui/day-names";
import { sendCountText } from "../ui/format";
import type { SendsGate } from "../ui/send-count";
import { sendsGate } from "../ui/send-count";
import { SketchThumb } from "../ui/sketch-thumb";

/** What a tile says when it holds no sketch. */
const MARK: Record<Exclude<SendState, "sketch">, string> = {
  "words-only": "Words only",
  withheld: "Withheld",
  "after-reveal": "Shows after the reveal",
};

const SEND_FIRST = "The sketches open after you send yours.";
const AFTER_REVEAL = "The sketches open when the photo is revealed.";

export function SendsScreen(): React.JSX.Element {
  const search = useSearch({ from: "/sends" });
  const latest = useDayQuery();

  if (latest.isPending) {
    return (
      <p className="subtle" aria-busy="true">
        Loading…
      </p>
    );
  }
  const day = search.day ?? latest.data?.day;
  if (day === undefined) {
    return (
      <section className="card page-narrow">
        <h1>No sketches yet</h1>
        {isRefusal(latest.error) ? (
          <p className="muted">No day is open right now.</p>
        ) : (
          <div className="notice notice-bad" role="alert">
            {friendlyMessage(latest.error)}
          </div>
        )}
        <BackLinks />
      </section>
    );
  }
  return <DaySends day={day} latest={latest.data} />;
}

function DaySends(props: {
  day: string;
  latest: DayView | undefined;
}): React.JSX.Element {
  const { day, latest } = props;
  const api = useApi();
  const names = useDayNames();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.getMe() });
  // With no day view the screen cannot say if the day is in play: the
  // server has the rule, and its refusal reads as "send first".
  const gate: SendsGate =
    latest === undefined ? "open" : sendsGate(latest, day);
  const sends = useInfiniteQuery({
    queryKey: ["day-sends", day],
    queryFn: ({ pageParam }) => api.getSends(day, pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => last.next_before ?? undefined,
    enabled: gate === "open",
    retry: false,
  });

  const inPlay = latest !== undefined && latest.day === day;
  const title =
    inPlay && latest.status !== "revealed"
      ? "Today's sketches"
      : `Sketches of ${names.long(day)}`;
  const count = inPlay
    ? sendCountText(latest.sends, latest.status === "open")
    : null;
  // A view that was out of date can pass the gate here and meet the
  // server's refusal: the server has the rule.
  const refused = gate === "open" && sends.isError && isRefusal(sends.error);
  const locked: SendsGate | null =
    gate !== "open" ? gate : refused ? "send-first" : null;

  const entries = sends.data?.pages.flatMap((page) => page.entries) ?? [];
  const total = sends.data?.pages[0]?.total ?? 0;

  return (
    <div className="sends">
      <header className="page-header">
        <h1 className="h-display">{title}</h1>
        {count === null ? null : (
          <p className="muted" data-testid="sends-count">
            {count}
          </p>
        )}
      </header>

      {locked !== null ? (
        <section className="sends-locked" data-testid="sends-locked">
          <p>{locked === "send-first" ? SEND_FIRST : AFTER_REVEAL}</p>
          {locked === "send-first" && inPlay ? (
            <div>
              <Link to="/today" className="btn btn-primary">
                Start today's sketch
              </Link>
            </div>
          ) : null}
        </section>
      ) : sends.isPending ? (
        <p className="subtle" aria-busy="true">
          Loading the sketches…
        </p>
      ) : sends.isError ? (
        <div className="notice notice-bad" role="alert">
          <p>{friendlyMessage(sends.error)}</p>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => void sends.refetch()}
          >
            Try again
          </button>
        </div>
      ) : entries.length === 0 ? (
        <p className="muted">No one sent on this day.</p>
      ) : (
        <>
          <ul className="sends-grid" aria-label="Sketches">
            {entries.map((entry) => (
              <SendTile
                key={entry.player}
                entry={entry}
                self={me.data?.player}
              />
            ))}
          </ul>
          <div className="sends-more">
            <p className="muted small" role="status">
              Showing {entries.length} of {total}
            </p>
            {sends.hasNextPage ? (
              <button
                type="button"
                className="btn btn-secondary"
                disabled={sends.isFetchingNextPage}
                onClick={() => void sends.fetchNextPage()}
              >
                {sends.isFetchingNextPage ? "Loading…" : "Show more"}
              </button>
            ) : null}
          </div>
        </>
      )}
      <BackLinks />
    </div>
  );
}

function SendTile(props: {
  entry: SendEntry;
  self: string | undefined;
}): React.JSX.Element {
  const { entry } = props;
  const own = entry.named && entry.player === props.self;
  const who = own ? "You" : entry.player;
  return (
    <li className="send-tile">
      <div className="send-sketch">
        {entry.state === "sketch" ? (
          <SketchThumb
            strokes={entry.strokes}
            label={own ? "Your sketch" : `Sketch by ${entry.player}`}
          />
        ) : (
          <p className="send-mark">{MARK[entry.state]}</p>
        )}
      </div>
      <div className="send-who">
        <AvatarCircle
          player={entry.player}
          avatarHash={entry.avatar_hash}
          size={24}
        />
        <span className="send-name" title={own ? undefined : entry.player}>
          {who}
        </span>
      </div>
    </li>
  );
}

function BackLinks(): React.JSX.Element {
  return (
    <p className="sends-back">
      <Link to="/">Back to home</Link>
    </p>
  );
}
