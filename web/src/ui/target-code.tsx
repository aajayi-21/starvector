/** The six-cell target code row (mock 1a) with the accent underline. */

export function TargetCode(props: { code: string }): React.JSX.Element {
  return (
    <div>
      <div
        style={{
          fontSize: 11,
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          color: "var(--color-accent)",
          marginBottom: 10,
        }}
      >
        Today's target
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        {[...props.code].map((cell, index) => (
          <span
            // The code is positional; the index is the identity.
            // biome-ignore lint/suspicious/noArrayIndexKey: positional cells
            key={index}
            style={{
              width: 58,
              height: 74,
              display: "grid",
              placeItems: "center",
              background: "var(--color-surface)",
              border: "1px solid var(--color-divider)",
              borderRadius: 8,
              fontSize: 36,
              fontWeight: 500,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {cell}
          </span>
        ))}
      </div>
      <div
        style={{
          width: 48,
          height: 2,
          background: "var(--color-accent)",
          marginTop: 12,
        }}
      />
    </div>
  );
}
