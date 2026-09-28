/**
 * A small section label above a group of controls. One quiet style
 * for each screen, from the theme's eyebrow class.
 */

export function Kicker(props: {
  children: React.ReactNode;
}): React.JSX.Element {
  return <div className="eyebrow">{props.children}</div>;
}
