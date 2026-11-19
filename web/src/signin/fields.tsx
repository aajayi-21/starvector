/**
 * The form pieces that the gate screen and the account screen share
 * (spec A2 §5.1): a password field with a control that shows the typed
 * password, and the one helper line that follows a field's rules.
 *
 * A password field never stops a paste and sets no maximum length: the
 * server does not cut a password short, thus the screen does not
 * either. A password manager finds the field by its `autocomplete`
 * token.
 */

import {
  Check,
  Eye,
  EyeSlash,
  Info,
  WarningCircle,
} from "@phosphor-icons/react";
import { useState } from "react";

import type { RuleCheck } from "./rules";

export function PasswordField(props: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** `current-password` for a held one, `new-password` for a new one. */
  autoComplete: "current-password" | "new-password";
  /** The id of the element that describes the field, if one does. */
  describedBy?: string;
  disabled?: boolean;
  /**
   * A small control at the right of the label row. It comes after the
   * field in the document, thus Tab goes from the field to it and not
   * through it.
   */
  labelAction?: React.ReactNode;
}): React.JSX.Element {
  const [shown, setShown] = useState(false);
  const Icon = shown ? EyeSlash : Eye;
  const hasAction = props.labelAction !== undefined;
  return (
    <div className={hasAction ? "field field-with-action" : "field"}>
      <label className="label" htmlFor={props.id}>
        {props.label}
      </label>
      <div className="password-row">
        <input
          id={props.id}
          className="input"
          type={shown ? "text" : "password"}
          autoComplete={props.autoComplete}
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          aria-describedby={props.describedBy}
          disabled={props.disabled}
          value={props.value}
          onChange={(event) => props.onChange(event.target.value)}
        />
        <button
          type="button"
          className="btn btn-secondary btn-icon"
          aria-label={shown ? `Hide ${props.label}` : `Show ${props.label}`}
          aria-pressed={shown}
          onClick={() => setShown((now) => !now)}
        >
          <Icon size={20} aria-hidden="true" />
        </button>
      </div>
      {hasAction ? (
        <div className="field-action">{props.labelAction}</div>
      ) : null}
    </div>
  );
}

/** A list of short rules as sentences: "Rule one. Rule two." */
function sentences(parts: ReadonlyArray<string>): string {
  return parts.map((part) => `${part}.`).join(" ");
}

/**
 * The rules of one field as one helper line with three states:
 *
 * - before the player types, the summary of the rules;
 * - with each rule met, the summary with a check mark;
 * - with text in the field and a rule broken, each broken rule by name.
 *
 * The state is in the words too (the broken rules, or "(met)"), thus
 * it does not depend on the icon or its color. The line is a polite
 * live region: a screen reader says it when its words change.
 */
export function RuleList(props: {
  id: string;
  checks: ReadonlyArray<RuleCheck>;
  /** Rules the screen cannot check; the server answers for them. */
  notes?: ReadonlyArray<string>;
  /** The line before the player types. The default lists each rule. */
  summary?: string;
  /**
   * True when the field has text. The default reads the checks: a
   * field with a met rule has text.
   */
  typed?: boolean;
  /** A rule of `notes` that the server refused for the typed value. */
  refused?: string;
}): React.JSX.Element {
  const summary =
    props.summary ??
    sentences([
      ...props.checks.map((check) => check.label),
      ...(props.notes ?? []),
    ]);
  const typed = props.typed ?? props.checks.some((check) => check.ok);
  const broken = [
    ...props.checks.filter((check) => !check.ok).map((check) => check.label),
    ...(props.refused === undefined ? [] : [props.refused]),
  ];
  const state =
    props.refused !== undefined || (typed && broken.length > 0)
      ? "broken"
      : typed
        ? "met"
        : "neutral";
  const Icon =
    state === "broken" ? WarningCircle : state === "met" ? Check : Info;
  return (
    <p
      id={props.id}
      className={
        state === "neutral" ? "rule-hint" : `rule-hint rule-hint-${state}`
      }
      aria-live="polite"
      aria-atomic="true"
    >
      <Icon
        size={16}
        weight={state === "met" ? "bold" : "regular"}
        aria-hidden="true"
      />
      <span>
        {state === "broken" ? sentences(broken) : summary}
        {state === "met" ? (
          <span className="visually-hidden"> (met)</span>
        ) : null}
      </span>
    </p>
  );
}
