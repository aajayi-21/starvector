/**
 * The quiet sky behind the home screen: a canvas of sparse stars that
 * twinkle a little. It is a picture with nothing to read, and it holds
 * no data. sky/home.ts places the stars; this module draws them.
 *
 * The sky is still under reduced motion, and where the browser cannot
 * say whether the canvas is on the screen. It draws only while it is
 * in view.
 */

import { randomOf } from "./core";
import { type QuietStar, quietField } from "./home";

export interface QuietSky {
  dispose(): void;
}

const STAR = "#f3f5fb";
const HALO = "#a9c1ff";
const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

export function createQuietSky(
  canvas: HTMLCanvasElement,
  seed: number,
): QuietSky {
  const context = canvas.getContext("2d");
  const reduce =
    typeof window.matchMedia === "function" &&
    window.matchMedia(REDUCED_MOTION).matches;
  let width = 0;
  let height = 0;
  let dpr = 1;
  let stars: QuietStar[] = [];
  let frame = 0;
  let running = false;
  let disposed = false;

  function layout(): void {
    width = canvas.clientWidth || 1024;
    height = canvas.clientHeight || 640;
    dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    // The same player gets the same sky at each size of window.
    stars = quietField(width, height, randomOf(seed));
  }

  function draw(time: number): void {
    if (context === null) {
      return;
    }
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, width, height);
    for (const star of stars) {
      const twinkle = reduce
        ? 0.9
        : 0.82 + 0.18 * Math.sin(time * star.speed + star.phase);
      const x = star.x * width;
      const y = star.y * height;
      if (star.bright) {
        // A soft halo in two steps, and two thin rays.
        context.fillStyle = HALO;
        context.globalAlpha = 0.05 * twinkle;
        context.beginPath();
        context.arc(x, y, star.size * 7, 0, 6.283);
        context.fill();
        context.globalAlpha = 0.12 * twinkle;
        context.beginPath();
        context.arc(x, y, star.size * 3, 0, 6.283);
        context.fill();
        context.fillStyle = STAR;
        context.globalAlpha = 0.22 * twinkle;
        const ray = star.size * 7;
        context.fillRect(x - ray, y - 0.4, ray * 2, 0.8);
        context.fillRect(x - 0.4, y - ray, 0.8, ray * 2);
      }
      context.fillStyle = STAR;
      context.globalAlpha = star.alpha * twinkle;
      context.beginPath();
      context.arc(x, y, star.size, 0, 6.283);
      context.fill();
    }
    context.globalAlpha = 1;
  }

  function tick(now: number): void {
    frame = 0;
    if (disposed || !running) {
      return;
    }
    draw(now / 1000);
    frame = window.requestAnimationFrame(tick);
  }

  function start(): void {
    if (running || reduce) {
      return;
    }
    running = true;
    frame = window.requestAnimationFrame(tick);
  }

  function stop(): void {
    running = false;
    if (frame !== 0) {
      window.cancelAnimationFrame(frame);
      frame = 0;
    }
  }

  layout();
  draw(0);

  const resized =
    typeof ResizeObserver === "function"
      ? new ResizeObserver(() => {
          if (canvas.clientWidth !== width || canvas.clientHeight !== height) {
            layout();
            draw(0);
          }
        })
      : null;
  resized?.observe(canvas);

  // With no way to know that the canvas is in view, the sky is still.
  const seen =
    typeof IntersectionObserver === "function"
      ? new IntersectionObserver((entries) => {
          if (entries.some((entry) => entry.isIntersecting)) {
            start();
          } else {
            stop();
          }
        })
      : null;
  seen?.observe(canvas);

  return {
    dispose() {
      disposed = true;
      stop();
      resized?.disconnect();
      seen?.disconnect();
    },
  };
}
