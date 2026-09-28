/**
 * The words card (spec A1 §6, copy per spec BR1 §6): a word or short
 * phrase for each thing that comes to mind. The list state stays in
 * the screen (the daily draft saves it); the line being typed is this
 * card's own. Enter adds, and so does the Add button — a phone
 * keyboard does not always show that Enter adds.
 */

import { X } from "@phosphor-icons/react";
import { useState } from "react";

export function ImpressionsCard(props: {
  impressions: ReadonlyArray<string>;
  onAdd: (text: string) => void;
  onRemoveAt: (index: number) => void;
}): React.JSX.Element {
  const { impressions, onAdd, onRemoveAt } = props;
  const [input, setInput] = useState("");

  const add = () => {
    const text = input.trim();
    if (text !== "") {
      onAdd(text);
      setInput("");
    }
  };

  return (
    <section className="card" aria-labelledby="words-heading">
      <div className="stack-sm">
        <h3 id="words-heading">Words</h3>
        <p className="hint" id="words-hint">
          A word or short phrase for each thing that comes to mind.
        </p>
      </div>
      <div className="row" style={{ flexWrap: "nowrap" }}>
        <input
          className="input"
          aria-label="Add a word"
          aria-describedby="words-hint"
          placeholder="e.g. tall, cold, metal"
          maxLength={200}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.nativeEvent.isComposing) {
              return;
            }
            if (event.key === "Enter") {
              event.preventDefault();
              add();
            }
          }}
        />
        <button
          type="button"
          className="btn btn-secondary"
          disabled={input.trim() === ""}
          onClick={add}
        >
          Add
        </button>
      </div>
      {impressions.length === 0 ? null : (
        <ul
          className="row"
          style={{ gap: 8, margin: 0, padding: 0, listStyle: "none" }}
        >
          {impressions.map((text, index) => (
            <li
              key={`${text}-${
                // biome-ignore lint/suspicious/noArrayIndexKey: duplicates allowed
                index
              }`}
              className="badge"
              style={{
                fontSize: 14,
                fontWeight: 500,
                color: "var(--text)",
                padding: "4px 4px 4px 12px",
              }}
            >
              {text}
              <button
                type="button"
                aria-label={`Remove ${text}`}
                onClick={() => onRemoveAt(index)}
                className="btn btn-ghost"
                style={{ minHeight: 26, padding: 4, borderRadius: 999 }}
              >
                <X size={14} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
