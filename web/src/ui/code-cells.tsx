/** The six-character session code, one cell for each character. */

export function CodeCells(props: {
  code: string;
  small?: boolean;
}): React.JSX.Element {
  return (
    <div
      className={
        props.small === true ? "code-cells code-cells-small" : "code-cells"
      }
      role="img"
      aria-label={`Code ${[...props.code].join(" ")}`}
    >
      {[...props.code].map((cell, index) => (
        // The code is positional; the index is the identity.
        // biome-ignore lint/suspicious/noArrayIndexKey: positional cells
        <span key={index} className="code-cell" aria-hidden="true">
          {cell}
        </span>
      ))}
    </div>
  );
}
