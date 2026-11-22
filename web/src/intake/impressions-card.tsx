/**
 * The words card (spec A1 §6, copy per spec BR1 §6): a word or short
 * phrase for each thing that comes to mind. The list and the line being
 * typed stay in the screen: the daily draft saves both, and the review
 * step offers a word typed and not added (spec PL1 §8). Enter adds, and
 * so does the Add button — a phone keyboard does not always show that
 * Enter adds.
 */

import { X } from "@phosphor-icons/react";

export function ImpressionsCard(props: {
  impressions: ReadonlyArray<string>;
  input: string;
  onInputChange: (text: string) => void;
  onAdd: (text: string) => void;
  onRemoveAt: (index: number) => void;
}): React.JSX.Element {
  const { impressions, input, onInputChange, onAdd, onRemoveAt } = props;

  const add = () => {
    const text = input.trim();
    if (text !== "") {
      onAdd(text);
      onInputChange("");
    }
  };

  return (
    <section className="words-block" aria-labelledby="words-heading">
      <h3 id="words-heading">Words</h3>
      <div className="words-entry">
        <input
          className="input"
          aria-label="Add a word"
          aria-describedby="words-hint"
          placeholder="tall, cold, metal"
          maxLength={200}
          value={input}
          onChange={(event) => onInputChange(event.target.value)}
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
      {/* The advice is for the first word: after that the words on the
          screen say it, and the line stays for a reader of the page. */}
      <p
        className={impressions.length === 0 ? "subtle tiny" : "visually-hidden"}
        id="words-hint"
      >
        One word or short phrase at a time.
      </p>
      {impressions.length === 0 ? null : (
        <ul className="chips">
          {impressions.map((text, index) => (
            <li
              key={`${text}-${
                // biome-ignore lint/suspicious/noArrayIndexKey: duplicates allowed
                index
              }`}
              className="chip"
            >
              {text}
              <button
                type="button"
                aria-label={`Remove ${text}`}
                onClick={() => onRemoveAt(index)}
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
