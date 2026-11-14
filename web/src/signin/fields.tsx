/**
 * The form pieces that the gate screen and the account screen share
 * (spec A2 §5.1): a password field with a control that shows the typed
 * password, and a rule list that follows the typed value.
 *
 * A password field never stops a paste and sets no maximum length: the
 * server does not cut a password short, thus the screen does not
 * either. A password manager finds the field by its `autocomplete`
 * token.
 */

import { Check, Circle, Eye, EyeSlash } from "@phosphor-icons/react";
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
}): React.JSX.Element {
  const [shown, setShown] = useState(false);
  const Icon = shown ? EyeSlash : Eye;
  return (
    <div className="field">
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
    </div>
  );
}

/**
 * The rules of one field, each with its state. The state is in the
 * text too ("met" or "not met yet"), thus it does not depend on the
 * icon or its color.
 */
export function RuleList(props: {
  id: string;
  checks: ReadonlyArray<RuleCheck>;
  /** Rules the screen cannot check; the server answers for them. */
  notes?: ReadonlyArray<string>;
}): React.JSX.Element {
  return (
    <ul id={props.id} className="rule-list">
      {props.checks.map((check) => {
        const Icon = check.ok ? Check : Circle;
        return (
          <li key={check.id} className={check.ok ? "rule-ok" : undefined}>
            <Icon
              size={16}
              weight={check.ok ? "bold" : "regular"}
              aria-hidden="true"
            />
            <span>
              {check.label}
              <span className="visually-hidden">
                {check.ok ? " (met)" : " (not met yet)"}
              </span>
            </span>
          </li>
        );
      })}
      {(props.notes ?? []).map((note) => (
        <li key={note}>
          <Circle size={16} aria-hidden="true" />
          <span>{note}</span>
        </li>
      ))}
    </ul>
  );
}
