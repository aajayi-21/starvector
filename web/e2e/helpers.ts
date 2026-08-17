import type { Page } from "@playwright/test";

/** Kept equal to serve_fixture.py by hand. */
export const SERVER = "http://127.0.0.1:8199";
export const OPERATOR_TOKEN = "e2e-operator-token";
export const OPERATOR_HEADERS = {
  Authorization: `Bearer ${OPERATOR_TOKEN}`,
};
export const TOKENS = {
  ade: `ade.${"1".repeat(43)}`,
  bru: `bru.${"2".repeat(43)}`,
};

/**
 * Plant the session cookie, in the manner the invite gate does.
 *
 * The fixture mints players, so every player surface refuses
 * without one. Cookies ignore ports, thus a single 127.0.0.1 entry
 * covers the app on 4173 and the server on 8199 — which is why
 * `page.request` calls at the server keep working.
 *
 * This is the ambient path. One spec walks GET /join/{token} for
 * real, which is the only place the server's own Set-Cookie is
 * exercised in a browser.
 */
export async function signIn(
  page: Page,
  token: string = TOKENS.ade,
): Promise<void> {
  await page.context().addCookies([
    {
      name: "sv_session",
      value: token,
      domain: "127.0.0.1",
      path: "/",
    },
  ]);
}

/** The offline posture: anything off-loopback is aborted. */
export async function blockExternalHosts(page: Page): Promise<void> {
  await page.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.hostname !== "127.0.0.1" && url.hostname !== "localhost") {
      return route.abort();
    }
    return route.continue();
  });
}

/** Draw one stroke across the sketch canvas in fractional coords. */
export async function drawStroke(
  page: Page,
  from: readonly [number, number],
  to: readonly [number, number],
): Promise<void> {
  const canvas = page.getByTestId("sketch-canvas");
  const box = await canvas.boundingBox();
  if (box === null) {
    throw new Error("the sketch canvas is not visible");
  }
  const at = (f: readonly [number, number]) =>
    [box.x + box.width * f[0], box.y + box.height * f[1]] as const;
  const [x0, y0] = at(from);
  const [x1, y1] = at(to);
  await page.mouse.move(x0, y0);
  await page.mouse.down();
  await page.mouse.move(x1, y1, { steps: 8 });
  await page.mouse.up();
}

export async function canvasPoint(
  page: Page,
  fraction: readonly [number, number],
): Promise<readonly [number, number]> {
  const box = await page.getByTestId("sketch-canvas").boundingBox();
  if (box === null) {
    throw new Error("the sketch canvas is not visible");
  }
  return [
    box.x + box.width * fraction[0],
    box.y + box.height * fraction[1],
  ] as const;
}
