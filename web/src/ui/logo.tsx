/**
 * The logo mark (spec W1 ruling 7, the five-ray nav mini), drawn in
 * currentColor so it takes the theme's accent in light and dark. The
 * vendored SVG files hold the Nord frost fill, which is too faint on
 * a light ground.
 */

import { useId } from "react";

export function LogoMark(props: { size?: number }): React.JSX.Element {
  const size = props.size ?? 22;
  // Each instance needs its own marker id: two marks on one page
  // must not share an arrowhead definition.
  const marker = `ah-${useId().replaceAll(":", "")}`;
  return (
    <svg
      className="brand-mark"
      viewBox="0 0 96 96"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      aria-hidden="true"
    >
      <defs>
        <marker
          id={marker}
          viewBox="0 0 10 10"
          refX="3.5"
          refY="5"
          markerWidth="2.8"
          markerHeight="2.8"
          orient="auto"
        >
          <path d="M0 0.8 L7.5 5 L0 9.2 Z" fill="currentColor" stroke="none" />
        </marker>
      </defs>
      <circle cx="48" cy="34" r="16" strokeWidth="6" />
      <g strokeWidth="6" strokeLinecap="round">
        <line x1="48" y1="12" x2="48" y2="7" markerEnd={`url(#${marker})`} />
        <line x1="70" y1="34" x2="75" y2="34" markerEnd={`url(#${marker})`} />
        <line x1="26" y1="34" x2="21" y2="34" markerEnd={`url(#${marker})`} />
        <line
          x1="63"
          y1="19"
          x2="66.5"
          y2="15.5"
          markerEnd={`url(#${marker})`}
        />
        <line
          x1="33"
          y1="19"
          x2="29.5"
          y2="15.5"
          markerEnd={`url(#${marker})`}
        />
      </g>
      <path
        d="M48 50 C45 60 52 64 48 72 C45 79 36 82 30 78"
        strokeWidth="6"
        strokeLinecap="round"
      />
    </svg>
  );
}
