/**
 * The impressions card (spec A1 §6): extracted from the daily
 * screen so practice mounts the same input. The list state stays
 * in the screen (the daily draft autosaves it); the in-progress
 * input line is this card's own.
 */

import { useState } from "react";

import { Kicker } from "../ui/kicker";

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
    <div className="card">
      <Kicker>Impressions</Kicker>
      <input
        className="input"
        placeholder="one impression — Enter commits"
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
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {impressions.map((text, index) => (
          <div
            key={`${text}-${
              // biome-ignore lint/suspicious/noArrayIndexKey: duplicates allowed
              index
            }`}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 13,
              padding: "6px 8px",
              background: "var(--color-neutral-900)",
              borderRadius: 6,
            }}
          >
            <span
              style={{
                width: 5,
                height: 5,
                borderRadius: "50%",
                background: "var(--color-accent)",
                flex: "none",
              }}
            />
            <span style={{ flex: 1 }}>{text}</span>
            <button
              type="button"
              title="remove"
              aria-label={`remove impression ${text}`}
              onClick={() => onRemoveAt(index)}
              style={{
                border: "none",
                background: "none",
                color: "var(--color-neutral-500)",
                cursor: "pointer",
                fontSize: 14,
                padding: "0 2px",
              }}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
