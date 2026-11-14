import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RecoveryCodeStep } from "../../src/signin/recovery-code-step";

const CODE = "ABCD-EFGH-JKMN-PQRS-TUVW-XYZ2";

/** jsdom has no clipboard: plant one, or take it away. */
function plantClipboard(writeText: ((text: string) => Promise<void>) | null) {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: writeText === null ? undefined : { writeText },
  });
}

afterEach(() => {
  plantClipboard(null);
  window.localStorage.clear();
});

describe("the recovery-code step (spec A2 §3.1 step 4, §6)", () => {
  it("shows the code in six groups of four", () => {
    render(<RecoveryCodeStep code={CODE} onDone={() => undefined} />);
    const shown = screen.getByTestId("recovery-code");
    const groups = [...shown.querySelectorAll("span")].map(
      (group) => group.textContent,
    );
    expect(groups).toEqual(["ABCD", "EFGH", "JKMN", "PQRS", "TUVW", "XYZ2"]);
  });

  it("says the code does not show again and what it is for", () => {
    render(<RecoveryCodeStep code={CODE} onDone={() => undefined} />);
    expect(screen.getByText("It will not be shown again.")).toBeDefined();
    expect(
      screen.getByText(/the only way back into your account if you lose your/),
    ).toBeDefined();
    // No earlier code to speak of at a sign-up.
    expect(screen.queryByText(/has stopped working/)).toBeNull();
  });

  it("says the earlier code is dead when it replaces one", () => {
    render(<RecoveryCodeStep code={CODE} replaces onDone={() => undefined} />);
    expect(screen.getByText(/had before has stopped working/)).toBeDefined();
  });

  it("continues on the `I have my code` click and on nothing else", () => {
    const done = vi.fn();
    plantClipboard(() => Promise.resolve());
    render(<RecoveryCodeStep code={CODE} onDone={done} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy the code" }));
    fireEvent.keyDown(document.body, { key: "Enter" });
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(done).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "I have my code" }));
    expect(done).toHaveBeenCalledTimes(1);
  });

  it("copies the code with its hyphens and says so", async () => {
    const copied: string[] = [];
    plantClipboard((text) => {
      copied.push(text);
      return Promise.resolve();
    });
    render(<RecoveryCodeStep code={CODE} onDone={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy the code" }));
    expect(await screen.findByText("Copied.")).toBeDefined();
    expect(copied).toEqual([CODE]);
  });

  it("says to copy by hand when the browser refuses the clipboard", async () => {
    render(<RecoveryCodeStep code={CODE} onDone={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy the code" }));
    expect(await screen.findByText(/copy it by hand/)).toBeDefined();
    plantClipboard(() => Promise.reject(new Error("denied")));
    fireEvent.click(screen.getByRole("button", { name: "Copy the code" }));
    await waitFor(() =>
      expect(screen.getByText(/copy it by hand/)).toBeDefined(),
    );
  });

  it("moves focus to its heading and keeps the code out of storage", () => {
    render(<RecoveryCodeStep code={CODE} onDone={() => undefined} />);
    expect(document.activeElement?.textContent).toBe("Save your recovery code");
    const kept = Object.values(window.localStorage).join(" ");
    expect(kept).not.toContain("ABCD");
  });
});
