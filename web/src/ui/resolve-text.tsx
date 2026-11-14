/**
 * Text that resolves out of noise (spec H1 §5): each letter starts
 * blurred, offset, and faint, and settles at its own random delay.
 * The real text sits in a visually hidden element for assistive
 * technology, and the letters are hidden from it. Under
 * `prefers-reduced-motion: reduce` the CSS draws the settled text.
 */

import { Fragment, useMemo } from "react";

import { RESOLVE_MS } from "../screens/greeting-constants";

export type Random = () => number;

interface Letter {
  char: string;
  delayMs: number;
  offsetPx: number;
}

/** The share of the total time that the delays may use. */
const DELAY_SHARE = 0.5;

function lettersOf(text: string, random: Random): Letter[] {
  return Array.from(text).map((char) => ({
    char,
    delayMs: Math.round(random() * RESOLVE_MS * DELAY_SHARE),
    offsetPx: Math.round((random() - 0.5) * 16),
  }));
}

function wordsOf(letters: Letter[]): Letter[][] {
  const words: Letter[][] = [[]];
  for (const letter of letters) {
    if (letter.char === " ") {
      words.push([]);
    } else {
      words[words.length - 1]?.push(letter);
    }
  }
  return words;
}

export function ResolveText(props: {
  text: string;
  /** The random source. A test passes a fixed one. */
  random?: Random;
}): React.JSX.Element {
  const { text, random = Math.random } = props;
  // The delays are drawn once for each text, so a rerender does not
  // restart the effect. `random` is left out of the keys on purpose.
  // biome-ignore lint/correctness/useExhaustiveDependencies: see above
  const words = useMemo(() => wordsOf(lettersOf(text, random)), [text]);
  const resolveMs = RESOLVE_MS * (1 - DELAY_SHARE);
  return (
    <>
      <span className="visually-hidden">{text}</span>
      <span aria-hidden="true" className="resolve-text">
        {words.map((word, wordIndex) => (
          // The words never reorder: the key is the position. The space
          // sits between the word spans, because a trailing space inside
          // an inline-block collapses and the words would run together.
          // biome-ignore lint/suspicious/noArrayIndexKey: see above
          <Fragment key={wordIndex}>
            {wordIndex > 0 ? " " : null}
            <span className="resolve-word">
              {word.map((letter, letterIndex) => (
                <span
                  // biome-ignore lint/suspicious/noArrayIndexKey: see above
                  key={letterIndex}
                  className="resolve-letter"
                  style={
                    {
                      "--resolve-delay": `${letter.delayMs}ms`,
                      "--resolve-ms": `${resolveMs}ms`,
                      "--resolve-dy": `${letter.offsetPx}px`,
                    } as React.CSSProperties
                  }
                >
                  {letter.char}
                </span>
              ))}
            </span>
          </Fragment>
        ))}
      </span>
    </>
  );
}
