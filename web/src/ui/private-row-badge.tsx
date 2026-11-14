/**
 * The mark on a daily-board row that no other player gets (spec A2
 * §9.5): the caller's own row while the caller is below the floor.
 * The two daily boards — the leaderboard screen and the reveal
 * screen — share it, so the words stay equal.
 */

export function PrivateRowBadge(): React.JSX.Element {
  return (
    <span className="badge badge-warn" style={{ marginLeft: 8 }}>
      Only you can see this row
    </span>
  );
}
