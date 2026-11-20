/**
 * The three parts of a sign-up (spec A2 §3.1) as one line of stars
 * above the form: the name and the password, the recovery code, and
 * the first day. The sign-up form shows it at part 1, and the
 * recovery-code step that follows a sign-up shows it at part 2. Part 3
 * is the app itself, thus no screen shows the line at part 3.
 *
 * A done part is a bright star, the current part has a halo, and a part
 * to come is a ring. The words say the state too: the current part has
 * `aria-current`, and a done part says that it is done.
 */

const PARTS: ReadonlyArray<string> = [
  "Name and password",
  "Recovery code",
  "Your first day",
];

export function SignupProgress(props: {
  /** The part the player is at: 1 or 2. */
  current: 1 | 2;
}): React.JSX.Element {
  return (
    <ol className="signup-progress" aria-label="Creating your account">
      {PARTS.map((part, index) => {
        const number = index + 1;
        const done = number < props.current;
        const here = number === props.current;
        return (
          <li
            key={part}
            className={
              done
                ? "signup-part is-done"
                : here
                  ? "signup-part"
                  : "signup-part is-pending"
            }
            aria-current={here ? "step" : undefined}
          >
            {part}
            {done ? <span className="visually-hidden"> (done)</span> : null}
          </li>
        );
      })}
    </ol>
  );
}
