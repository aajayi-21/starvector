/**
 * The avatar circle (spec A1): the stored picture when the account
 * holds one, else the first two characters of the username - the one
 * name of a player (spec A2 ruling 3). One component serves
 * the nav, the account screen, and the board rows (D5 as ruled
 * 2026-08-21), so the fallback rule lives in one place.
 */

import { useApi } from "../api/client";
import { streakTier } from "./streak";

/** The ring and the gap, in pixels, for an avatar of this outer size. */
function ringMetrics(size: number): { ring: number; gap: number } {
  if (size >= 60) {
    return { ring: 4, gap: 3 };
  }
  return { ring: 2, gap: size >= 30 ? 2 : 1 };
}

/**
 * The avatar with its streak ring (spec H1 §4). The outer size stays
 * `size` at each tier, so a row does not move when a streak grows.
 * A screen that does not hold the streak passes none and draws the
 * plain circle.
 */
export function AvatarCircle(props: {
  player: string;
  avatarHash: string | null;
  size: number;
  streak?: number;
}): React.JSX.Element {
  const tier = streakTier(props.streak ?? 0);
  if (tier === 0) {
    return <AvatarPicture {...props} />;
  }
  const { ring, gap } = ringMetrics(props.size);
  return (
    <span
      className="streak-ring"
      data-tier={tier}
      style={{ width: props.size, height: props.size, padding: ring }}
    >
      <span className="streak-ring-gap" style={{ padding: gap }}>
        <AvatarPicture {...props} size={props.size - 2 * (ring + gap)} />
      </span>
    </span>
  );
}

function AvatarPicture(props: {
  player: string;
  avatarHash: string | null;
  size: number;
}): React.JSX.Element {
  const api = useApi();
  const { player, avatarHash, size } = props;
  if (avatarHash !== null) {
    return (
      <img
        src={api.avatarUrl(player, avatarHash)}
        alt=""
        width={size}
        height={size}
        style={{
          width: size,
          height: size,
          borderRadius: "50%",
          objectFit: "cover",
          flex: "none",
        }}
      />
    );
  }
  return (
    <span
      aria-hidden="true"
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        background: "var(--accent-soft)",
        color: "var(--accent-text)",
        display: "grid",
        placeItems: "center",
        fontSize: Math.max(9, Math.round(size * 0.4)),
        fontWeight: 650,
        flex: "none",
      }}
    >
      {player.slice(0, 2).toUpperCase()}
    </span>
  );
}
