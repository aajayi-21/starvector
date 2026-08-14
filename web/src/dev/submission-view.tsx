/**
 * The stored-submission viewer: received time, trial id, the SVG
 * stroke replay (stroke color, else the group hue, else ink), the
 * impressions, groups and relations, and the pasted text.
 */

import type { WireRecord } from "../api/types";
import type { DevStored } from "./types";

const GROUPED_HUE = "#a3be8c";
const INK = "#eceff4";

function labelOf(record: WireRecord, groupId: string): string {
  const group = record.groups.find((row) => row.id === groupId);
  return group === undefined || group.label === ""
    ? groupId
    : `${group.label} (${group.id})`;
}

export function SubmissionView(props: {
  stored: DevStored;
}): React.JSX.Element {
  const { stored } = props;
  const record = stored.record;
  return (
    <div className="card" style={{ gap: 8 }}>
      <div
        style={{
          fontSize: 11,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--color-neutral-500)",
        }}
      >
        Stored submission
      </div>
      <div style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
        received {stored.received_at} · trial{" "}
        <span style={{ fontFamily: "ui-monospace, Menlo, monospace" }}>
          {stored.trial_id}
        </span>
      </div>
      <svg
        role="img"
        aria-label="stored sketch replay"
        viewBox="0 0 100 100"
        style={{
          width: 256,
          maxWidth: "100%",
          aspectRatio: "1 / 1",
          background: "#272c37",
          borderRadius: 8,
        }}
      >
        {record.canvas_strokes.map((stroke, index) => (
          <polyline
            // Strokes are positional; the index is the identity.
            // biome-ignore lint/suspicious/noArrayIndexKey: positional
            key={index}
            points={stroke.points
              .map(
                ([x, y]) => `${(x * 100).toFixed(2)},${(y * 100).toFixed(2)}`,
              )
              .join(" ")}
            fill="none"
            strokeWidth={1}
            stroke={
              stroke.color ??
              (stroke.group_id !== null && stroke.group_id !== undefined
                ? GROUPED_HUE
                : INK)
            }
          />
        ))}
      </svg>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>
        {record.impressions.map((text) => (
          <li key={text}>impression: {text}</li>
        ))}
        {record.groups.map((group) => (
          <li key={group.id}>group: {labelOf(record, group.id)}</li>
        ))}
        {record.relations.map((relation, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: positional
          <li key={index}>
            relation: {labelOf(record, relation.of[0])} {relation.relation}{" "}
            {labelOf(record, relation.of[1])}
          </li>
        ))}
      </ul>
      {record.pasted_text === null ? null : (
        <div style={{ fontSize: 13 }}>pasted: {record.pasted_text}</div>
      )}
    </div>
  );
}
