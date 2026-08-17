/**
 * The card kicker: the small uppercase label above a card's body
 * (mock screens 1a-1f). Four screens held a byte-identical private
 * copy of this; a fifth arrived with the leaderboard.
 *
 * Distinct from Nocturne's `.card-kicker` class, which is accent
 * coloured and belongs to the refusal cards.
 */

export function Kicker(props: {
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <div
      style={{
        fontSize: 11,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color: "var(--color-neutral-500)",
      }}
    >
      {props.children}
    </div>
  );
}
