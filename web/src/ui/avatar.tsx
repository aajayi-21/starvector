/**
 * The avatar circle (spec A1): the stored picture when the account
 * holds one, else the display-name initials. One component serves
 * the nav, the account screen, and the board rows (D5 as ruled
 * 2026-08-21), so the fallback rule lives in one place.
 */

import { useApi } from "../api/client";

export function AvatarCircle(props: {
  player: string;
  displayName: string;
  avatarHash: string | null;
  size: number;
}): React.JSX.Element {
  const api = useApi();
  const { player, displayName, avatarHash, size } = props;
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
        background: "var(--color-neutral-800)",
        color: "var(--color-neutral-200)",
        display: "grid",
        placeItems: "center",
        fontSize: Math.max(9, Math.round(size * 0.4)),
        fontWeight: 500,
        flex: "none",
      }}
    >
      {displayName.slice(0, 2).toUpperCase()}
    </span>
  );
}
