/**
 * The six-character code of a day, as plain spaced type. It is a thing
 * to read and not a thing to type, so it has no cells and no edges: a
 * row of boxes looks like six fields (owner ruling 2026-11-20).
 */

export function DayCode(props: {
  code: string;
  /** The size on the home screen; the default is the size beside text. */
  large?: boolean;
}): React.JSX.Element {
  return (
    <p
      className={
        props.large === true ? "code day-code is-large" : "code day-code"
      }
      role="img"
      aria-label={`Code ${[...props.code].join(" ")}`}
    >
      {props.code}
    </p>
  );
}
