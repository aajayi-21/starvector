/**
 * The engine of the results sky: the one place that moves its nodes.
 *
 * React renders the nodes of the sky one time for each change of the
 * data (ui/results-sky.tsx). The engine sets their places on each
 * frame, so the drift of the drawings, the pointer, and the scroll out
 * of the sky cost no render. The geometry is in sky/core.ts, and the
 * engine does no more arithmetic than a blend between two places.
 *
 * The nodes it moves are marked in the tree: `data-sky="…"` names a
 * part, `data-sky-star` a day's star (with the words that stand over
 * it in `data-hover`), and `data-sky-fig` a day's drawing with the
 * place of its star in `data-ax` and `data-ay`.
 *
 * Positions in the sky are no data: a drawing may drift. The size of a
 * drawing, and each place on the chart, are data and hold still.
 */

import {
  chartPlace,
  chartStarRadius,
  clamp,
  ease,
  lerp,
  randomOf,
  type SkyBounds,
  type SkyRect,
  scatter,
  skyStarRadius,
  smooth,
} from "./core";

export interface SkyDay {
  /** The result, from 0 to 1. */
  p: number;
}

export interface SkyHandlers {
  /** A day was chosen, or the chosen day was let go (null). */
  onPick(index: number | null): void;
}

export interface Sky {
  /** Reads the drawings again, after React added or changed one. */
  syncFigures(): void;
  /** Marks the chosen day, and puts its words on the side away from it. */
  setPicked(index: number | null): void;
  dispose(): void;
}

/** The one breakpoint of app.css, kept equal by hand. */
const NARROW_WIDTH = 760;
/** The widest content of the app, as in app.css. */
const CONTENT_WIDTH = 1376;
/** How far the pointer reaches for a day, with a mouse and with a finger. */
const REACH_MOUSE = 24;
const REACH_TOUCH = 30;

interface FieldStar {
  x: number;
  y: number;
  depth: number;
  size: number;
  alpha: number;
  phase: number;
  speed: number;
}

export function createSky(
  stage: HTMLElement,
  days: ReadonlyArray<SkyDay>,
  seed: number,
  handlers: SkyHandlers,
): Sky {
  const space = stage.parentElement ?? stage;
  const part = <T extends Element>(name: string): T | null =>
    stage.querySelector<T>(`[data-sky="${name}"]`);
  const field = part<HTMLCanvasElement>("field");
  const context = field?.getContext("2d") ?? null;
  const figLayer = part<HTMLElement>("figs");
  const thread = part<SVGPolylineElement>("thread");
  const chance = part<SVGGElement>("chance");
  const frame = part<SVGGElement>("frame");
  const leader = part<SVGLineElement>("leader");
  const label = part<HTMLElement>("label");
  const plate = part<HTMLElement>("plate");
  const capSky = part<HTMLElement>("cap-sky");
  const capChart = part<HTMLElement>("cap-chart");
  const cue = part<HTMLElement>("cue");
  const stars = Array.from(
    stage.querySelectorAll<HTMLElement>("[data-sky-star]"),
  );
  const count = days.length;
  const reduce =
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
  // Frames run without a stop only where the sky can tell that it is
  // on the screen. Elsewhere a frame runs when something changed.
  const canWatch = typeof IntersectionObserver === "function";

  const array = (): Float32Array => new Float32Array(count);
  const centerX = array();
  const centerY = array();
  const size = array();
  const turn = array();
  const depth = array();
  const phase = array();
  const skyR = array();
  const anchorX = array();
  const anchorY = array();
  const offX = array();
  const offY = array();
  const has = array();
  const grow = array();
  const shine = array();
  const chartX = array();
  const chartY = array();
  const chartR = array();
  const nowX = array();
  const nowY = array();
  const nowR = array();
  let figs: Array<SVGSVGElement | null> = new Array(count).fill(null);
  let fieldStars: FieldStar[] = [];
  let width = 0;
  let height = 0;
  let narrow = false;
  let gutter = 40;
  let stickyTop = 0;
  let dpr = 1;
  let chart: SkyRect = { left: 0, top: 0, right: 0, bottom: 0 };
  let progress = 0;
  let pointerX = 0;
  let pointerY = 0;
  let targetX = 0;
  let targetY = 0;
  let hover = -1;
  let picked = -1;
  let pickedAt = 0;
  /** Where the mouse rests on the screen, or null. */
  let mouse: { x: number; y: number } | null = null;
  let raf = 0;
  let queued = false;
  let visible = true;
  let disposed = false;

  const set = (
    node: Element | null,
    attributes: Record<string, number | string>,
  ): void => {
    if (node === null) {
      return;
    }
    for (const [name, value] of Object.entries(attributes)) {
      node.setAttribute(name, String(value));
    }
  };

  function layout(): void {
    width = stage.clientWidth || 1024;
    height = stage.clientHeight || 640;
    narrow = width < NARROW_WIDTH;
    gutter = narrow ? 16 : Math.max(40, (width - CONTENT_WIDTH) / 2);
    stickyTop = Number.parseFloat(getComputedStyle(stage).top) || 0;
    dpr = Math.min(2, window.devicePixelRatio || 1);
    if (field !== null) {
      field.width = Math.round(width * dpr);
      field.height = Math.round(height * dpr);
    }
    // The title's corner and the hint at the foot stay clear.
    const bounds: SkyBounds = {
      left: gutter + 4,
      right: width - gutter - 4,
      top: 14,
      bottom: height - 14,
      keepOut: [
        {
          left: 0,
          top: 0,
          right: narrow ? width : gutter + 640,
          bottom: narrow ? 150 : 176,
        },
        {
          left: narrow ? 0 : width / 2 - 210,
          right: narrow ? width : width / 2 + 210,
          top: height - 88,
          bottom: height,
        },
      ],
    };
    const sky = scatter(
      days.map((day) => day.p),
      bounds,
      seed,
    );
    const top = narrow ? 200 : 196;
    chart = {
      left: gutter + (narrow ? 40 : 58),
      right: width - gutter - (narrow ? 8 : 92),
      top,
      bottom: Math.max(top + 120, height - (narrow ? 56 : 64)),
    };
    const random = randomOf(seed ^ 0x5eed);
    let best = 0;
    for (let index = 0; index < count; index += 1) {
      const p = (days[index] as SkyDay).p;
      centerX[index] = sky.x[index] as number;
      centerY[index] = sky.y[index] as number;
      size[index] = sky.size[index] as number;
      turn[index] = (random() - 0.5) * 0.34;
      depth[index] = 0.3 + (0.7 * (sky.size[index] as number)) / sky.largest;
      phase[index] = random() * Math.PI * 2;
      skyR[index] = skyStarRadius(sky.size[index] as number);
      const place = chartPlace(index, count, p, chart);
      chartX[index] = place.x;
      chartY[index] = place.y;
      chartR[index] = chartStarRadius(p, narrow);
      stars[index]?.style.setProperty(
        "--sky-r",
        `${(skyR[index] as number).toFixed(2)}px`,
      );
      if (p > (days[best] as SkyDay).p) {
        best = index;
      }
    }
    // The faint stars behind: no data, the same on each visit.
    const faint = randomOf(5);
    const many = clamp(Math.round((width * height) / 2500), 150, 520);
    fieldStars = Array.from({ length: many }, () => ({
      x: faint(),
      y: faint(),
      depth: 0.25 + faint() * 0.75,
      size: faint() < 0.07 ? 1.2 + faint() * 0.7 : 0.3 + faint() * 0.7,
      alpha: 0.22 + faint() * 0.6,
      phase: faint() * 6.28,
      speed: 0.4 + faint() * 1.4,
    }));
    // The frame of the chart: the two edges, the scale, and the dates.
    const lineLeft = chart.left - 14;
    const lineRight = narrow ? width - gutter : chart.right + 22;
    const middle = (chart.top + chart.bottom) / 2;
    set(part("edge-top"), {
      x1: lineLeft,
      x2: lineRight,
      y1: chart.top,
      y2: chart.top,
    });
    set(part("edge-foot"), {
      x1: lineLeft,
      x2: lineRight,
      y1: chart.bottom,
      y2: chart.bottom,
    });
    set(part("chance-line"), {
      x1: lineLeft,
      x2: lineRight,
      y1: middle,
      y2: middle,
    });
    set(part("scale-top"), { x: gutter, y: chart.top + 4 });
    set(part("scale-middle"), { x: gutter, y: middle + 4 });
    set(part("scale-foot"), { x: gutter, y: chart.bottom + 4 });
    set(part("chance-word"), { x: width - gutter, y: middle + 5 });
    set(part("date-first"), { x: chart.left, y: chart.bottom + 26 });
    set(part("date-middle"), {
      x: (chart.left + chart.right) / 2,
      y: chart.bottom + 26,
    });
    set(part("date-last"), { x: chart.right, y: chart.bottom + 26 });
    if (count > 0) {
      // The date of the best star sits before it, or after it when the
      // star is near the left edge.
      const before = (chartX[best] as number) > chart.left + 120;
      set(part("date-best"), {
        x:
          (chartX[best] as number) +
          (before ? -1 : 1) * ((chartR[best] as number) + 12),
        y: (chartY[best] as number) + 5,
        "text-anchor": before ? "end" : "start",
      });
    }
    syncFigures();
  }

  function syncFigures(): void {
    figs = new Array(count).fill(null);
    has.fill(0);
    for (const node of stage.querySelectorAll<SVGSVGElement>(
      "[data-sky-fig]",
    )) {
      const index = Number(node.dataset.index);
      if (!(index >= 0 && index < count)) {
        continue;
      }
      const side = size[index] as number;
      const ax = Number(node.dataset.ax) * side;
      const ay = Number(node.dataset.ay) * side;
      const fromMiddleX = ax - side / 2;
      const fromMiddleY = ay - side / 2;
      const angle = turn[index] as number;
      figs[index] = node;
      has[index] = 1;
      anchorX[index] = ax;
      anchorY[index] = ay;
      // From the middle of the drawing to its star, with the turn.
      offX[index] =
        fromMiddleX * Math.cos(angle) - fromMiddleY * Math.sin(angle);
      offY[index] =
        fromMiddleX * Math.sin(angle) + fromMiddleY * Math.cos(angle);
      node.style.width = `${side.toFixed(1)}px`;
      node.style.height = `${side.toFixed(1)}px`;
      node.style.transformOrigin = `${ax.toFixed(1)}px ${ay.toFixed(1)}px`;
      // A better result is a brighter drawing with a firmer line.
      shine[index] = 0.34 + 0.52 * (days[index] as SkyDay).p;
      node.style.setProperty("--sky-o", (shine[index] as number).toFixed(2));
      node.style.strokeWidth = `${clamp(0.75 + side / 230, 0.8, 1.9).toFixed(2)}px`;
      node.classList.toggle("is-small", side < 46);
      const dot = (clamp(side * 0.011, 0.8, 2.3) / side).toFixed(4);
      for (const circle of node.querySelectorAll("circle")) {
        circle.setAttribute("r", dot);
      }
    }
    request();
  }

  function drawField(time: number, toChart: number): void {
    if (context === null) {
      return;
    }
    const fade = lerp(1, 0.42, toChart);
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#f3f5fb";
    for (const star of fieldStars) {
      const twinkle = reduce
        ? 0.85
        : 0.65 + 0.35 * Math.sin(time * star.speed + star.phase);
      context.globalAlpha = star.alpha * twinkle * fade;
      context.beginPath();
      context.arc(
        star.x * width - pointerX * 22 * star.depth * (1 - toChart),
        star.y * height - pointerY * 16 * star.depth * (1 - toChart),
        star.size,
        0,
        6.283,
      );
      context.fill();
    }
    context.globalAlpha = 1;
  }

  function render(stamp: number): void {
    const time = stamp / 1000;
    const rect = space.getBoundingClientRect();
    const span = rect.height - height;
    const before = progress;
    progress = span > 0 ? clamp((stickyTop - rect.top) / span, 0, 1) : 0;
    const toChart = ease(clamp((progress - 0.06) / 0.86, 0, 1));
    // A day opened in the sky closes when the page leaves the sky, so
    // its words do not sit over the chart.
    if (picked >= 0 && pickedAt < 0.25 && progress > 0.4) {
      handlers.onPick(null);
    }
    const follow = reduce ? 1 : 0.075;
    pointerX += (targetX - pointerX) * follow;
    pointerY += (targetY - pointerY) * follow;
    drawField(time, toChart);
    // On the way to the chart each drawing folds into its star: it
    // shrinks about the star and fades.
    const figuresOn = progress < 0.44;
    const fold = 1 - 0.82 * smooth(progress, 0.02, 0.42);
    const drift = reduce ? 0 : 1;
    let points = "";
    for (let index = 0; index < count; index += 1) {
      // A drawing grows out of its star when its sketch arrives.
      const grown =
        (grow[index] as number) +
        ((has[index] as number) - (grow[index] as number)) *
          (reduce ? 1 : 0.09);
      grow[index] =
        Math.abs((has[index] as number) - grown) < 0.004
          ? (has[index] as number)
          : grown;
      // A large drawing is near: it moves more with the pointer.
      const near = depth[index] as number;
      const skyX =
        (centerX[index] as number) +
        (offX[index] as number) * grown -
        pointerX * 22 * near +
        drift * Math.sin(time * 0.23 + (phase[index] as number)) * 4.5 * near;
      const skyY =
        (centerY[index] as number) +
        (offY[index] as number) * grown -
        pointerY * 15 * near +
        drift *
          Math.cos(time * 0.19 + (phase[index] as number) * 1.7) *
          3.5 *
          near;
      const x = lerp(skyX, chartX[index] as number, toChart);
      const y = lerp(skyY, chartY[index] as number, toChart);
      const r = lerp(skyR[index] as number, chartR[index] as number, toChart);
      nowX[index] = x;
      nowY[index] = y;
      nowR[index] = r;
      const star = stars[index];
      if (star !== undefined) {
        star.style.transform = `translate(${x.toFixed(1)}px,${y.toFixed(1)}px) scale(${(r / (skyR[index] as number)).toFixed(3)})`;
      }
      const fig = figs[index];
      if (fig !== null && fig !== undefined && figuresOn) {
        fig.style.transform = `translate(${(x - (anchorX[index] as number)).toFixed(1)}px,${(y - (anchorY[index] as number)).toFixed(1)}px) rotate(${(turn[index] as number).toFixed(3)}rad) scale(${(fold * (0.25 + 0.75 * grown)).toFixed(3)})`;
        fig.style.opacity =
          grown < 1 ? (grown * (shine[index] as number)).toFixed(2) : "";
      }
      points += `${x.toFixed(1)},${y.toFixed(1)} `;
    }
    // The line of the chart comes in late, when the stars are near
    // their places.
    if (thread !== null) {
      thread.setAttribute("points", count > 1 ? points : "");
      thread.style.opacity = String(0.5 * smooth(toChart, 0.62, 1));
    }
    const frameIn = smooth(progress, 0.58, 0.96);
    if (chance !== null) {
      chance.style.opacity = String(frameIn * 0.9);
    }
    if (frame !== null) {
      frame.style.opacity = String(frameIn);
    }
    if (capSky !== null) {
      capSky.style.opacity = String(1 - smooth(progress, 0.3, 0.6));
    }
    if (capChart !== null) {
      capChart.style.opacity = String(smooth(progress, 0.55, 0.9));
    }
    if (cue !== null) {
      cue.style.opacity = String(
        picked >= 0 ? 0 : 1 - smooth(progress, 0, 0.18),
      );
    }
    if (figLayer !== null) {
      const figuresIn = 1 - smooth(progress, 0.04, 0.4);
      figLayer.style.opacity = String(figuresIn);
      figLayer.style.visibility = figuresIn > 0.01 ? "visible" : "hidden";
    }
    // The page moved under a mouse that rests: the day under it may be
    // a new one, or none.
    if (mouse !== null && Math.abs(progress - before) > 0.0005) {
      setHover(nearest(mouse.x, mouse.y, REACH_MOUSE));
    }
    placeLabel();
    placeLeader();
  }

  /** The middle of a day's drawing while the sky shows drawings. */
  function middleOf(index: number): { x: number; y: number; reach: number } {
    const drawn = progress < 0.2 && (grow[index] as number) > 0.5;
    return drawn
      ? {
          x: (nowX[index] as number) - (offX[index] as number),
          y: (nowY[index] as number) - (offY[index] as number),
          reach: (size[index] as number) * 0.5,
        }
      : {
          x: nowX[index] as number,
          y: nowY[index] as number,
          reach: (nowR[index] as number) + 10,
        };
  }

  function placeLabel(): void {
    if (label === null) {
      return;
    }
    const index = hover >= 0 && hover !== picked ? hover : -1;
    if (index < 0) {
      label.style.opacity = "0";
      return;
    }
    // The words stand over the whole drawing, or over the star alone.
    const at = middleOf(index);
    const above = at.y - at.reach - 26 > (narrow ? 150 : 176);
    const wide = label.offsetWidth || 90;
    label.style.transform = `translate(${clamp(at.x - wide / 2, 8, width - wide - 8).toFixed(1)}px,${(above ? at.y - at.reach - 26 : at.y + at.reach + 2).toFixed(1)}px)`;
    label.style.opacity = "1";
  }

  /** The hairline from the chosen star to its words. */
  function placeLeader(): void {
    if (leader === null) {
      return;
    }
    if (picked < 0 || plate === null) {
      leader.style.opacity = "0";
      return;
    }
    const words = plate.getBoundingClientRect();
    const sky = stage.getBoundingClientRect();
    const side = stage.dataset.side;
    const starX = nowX[picked] as number;
    const starY = nowY[picked] as number;
    let endX = 0;
    let endY = 0;
    if (narrow) {
      endX = clamp(
        starX,
        words.left - sky.left + 8,
        words.right - sky.left - 8,
      );
      endY =
        side === "top" ? words.bottom - sky.top + 10 : words.top - sky.top - 12;
    } else {
      endX =
        side === "left"
          ? words.right - sky.left + 14
          : words.left - sky.left - 16;
      endY = words.top - sky.top + 12;
    }
    const dx = endX - starX;
    const dy = endY - starY;
    const length = Math.hypot(dx, dy) || 1;
    const clear = (nowR[picked] as number) + 9;
    set(leader, {
      x1: starX + (dx / length) * clear,
      y1: starY + (dy / length) * clear,
      x2: endX,
      y2: endY,
    });
    leader.style.opacity = length > clear + 6 ? "0.55" : "0";
  }

  function tick(stamp: number): void {
    queued = false;
    if (disposed) {
      return;
    }
    render(stamp);
    if (!reduce && canWatch && visible) {
      request();
    }
  }

  function request(): void {
    if (queued || disposed) {
      return;
    }
    queued = true;
    raf = requestAnimationFrame(tick);
  }

  /** The day under a point of the screen, or -1. */
  function nearest(clientX: number, clientY: number, reach: number): number {
    const sky = stage.getBoundingClientRect();
    const x = clientX - sky.left;
    const y = clientY - sky.top;
    let found = -1;
    let least = Number.POSITIVE_INFINITY;
    // A press on the star of a drawing is that drawing, before any
    // neighbor whose middle is nearer.
    for (let index = 0; index < count; index += 1) {
      const distance = Math.hypot(
        (nowX[index] as number) - x,
        (nowY[index] as number) - y,
      );
      if (distance < (nowR[index] as number) + 11 && distance < least) {
        least = distance;
        found = index;
      }
    }
    if (found >= 0) {
      return found;
    }
    for (let index = 0; index < count; index += 1) {
      const at = middleOf(index);
      const distance = Math.hypot(at.x - x, at.y - y);
      if (distance < Math.max(reach, at.reach * 1.04) && distance < least) {
        least = distance;
        found = index;
      }
    }
    return found;
  }

  function setHover(index: number): void {
    if (index === hover) {
      return;
    }
    if (hover >= 0) {
      stars[hover]?.classList.remove("is-hover");
      if (hover !== picked) {
        figs[hover]?.classList.remove("is-on");
      }
    }
    hover = index;
    if (index >= 0) {
      stars[index]?.classList.add("is-hover");
      figs[index]?.classList.add("is-on");
      if (label !== null) {
        label.textContent = stars[index]?.dataset.hover ?? "";
      }
    }
    stage.style.cursor = index >= 0 ? "pointer" : "";
    request();
  }

  function setPicked(index: number | null): void {
    const next = index === null || index < 0 || index >= count ? -1 : index;
    if (picked >= 0) {
      stars[picked]?.classList.remove("is-picked");
      if (picked !== hover) {
        figs[picked]?.classList.remove("is-on");
      }
    }
    picked = next;
    figLayer?.classList.toggle("has-pick", next >= 0);
    if (next < 0) {
      delete stage.dataset.side;
      request();
      return;
    }
    pickedAt = progress;
    stars[next]?.classList.add("is-picked");
    figs[next]?.classList.add("is-on");
    // The words go to the side away from the drawing.
    const at = middleOf(next);
    stage.dataset.side = narrow
      ? at.y > height * 0.5
        ? "top"
        : "bottom"
      : at.x > width * 0.56
        ? "left"
        : "right";
    request();
  }

  const onMove = (event: PointerEvent): void => {
    const sky = stage.getBoundingClientRect();
    targetX = clamp(
      (event.clientX - sky.left - width / 2) / (width / 2),
      -1,
      1,
    );
    targetY = clamp(
      (event.clientY - sky.top - height / 2) / (height / 2),
      -1,
      1,
    );
    if (event.pointerType !== "touch") {
      const onWords = (event.target as Element | null)?.closest(
        '[data-sky="plate"]',
      );
      mouse = onWords ? null : { x: event.clientX, y: event.clientY };
      setHover(mouse === null ? -1 : nearest(mouse.x, mouse.y, REACH_MOUSE));
    }
    request();
  };
  const onLeave = (): void => {
    targetX = 0;
    targetY = 0;
    mouse = null;
    setHover(-1);
  };
  const onClick = (event: MouseEvent): void => {
    const target = event.target as Element | null;
    const star = target?.closest<HTMLElement>("[data-sky-star]");
    if (star) {
      // The keyboard presses a star itself.
      handlers.onPick(Number(star.dataset.index));
      return;
    }
    if (target?.closest('[data-sky="plate"]')) {
      return;
    }
    const index = nearest(event.clientX, event.clientY, REACH_TOUCH);
    handlers.onPick(index < 0 || index === picked ? null : index);
  };
  const onFocus = (event: FocusEvent): void => {
    const star = (event.target as Element | null)?.closest<HTMLElement>(
      "[data-sky-star]",
    );
    if (star) {
      setHover(Number(star.dataset.index));
    }
  };
  const onBlur = (): void => setHover(-1);
  const onKey = (event: KeyboardEvent): void => {
    if (event.key === "Escape" && picked >= 0) {
      handlers.onPick(null);
      return;
    }
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
      return;
    }
    const focused =
      document.activeElement?.closest<HTMLElement>("[data-sky-star]");
    const from =
      picked >= 0 ? picked : focused ? Number(focused.dataset.index) : -1;
    if (from < 0) {
      return;
    }
    // The arrows step through the days in order, as the buttons do.
    event.preventDefault();
    const to = clamp(
      from + (event.key === "ArrowRight" ? 1 : -1),
      0,
      count - 1,
    );
    if (picked >= 0) {
      handlers.onPick(to);
    } else {
      stars[to]?.focus();
    }
  };

  stage.addEventListener("pointermove", onMove);
  stage.addEventListener("pointerleave", onLeave);
  stage.addEventListener("click", onClick);
  stage.addEventListener("focusin", onFocus);
  stage.addEventListener("focusout", onBlur);
  document.addEventListener("keydown", onKey);
  window.addEventListener("scroll", request, { passive: true });
  const resize =
    typeof ResizeObserver === "function"
      ? new ResizeObserver(() => {
          layout();
          if (picked >= 0) {
            setPicked(picked);
          }
        })
      : null;
  const watch = canWatch
    ? new IntersectionObserver((entries) => {
        visible = entries[0]?.isIntersecting === true;
        if (visible) {
          request();
        }
      })
    : null;
  layout();
  resize?.observe(stage);
  watch?.observe(space);
  request();

  return {
    syncFigures,
    setPicked,
    dispose(): void {
      disposed = true;
      if (typeof cancelAnimationFrame === "function") {
        cancelAnimationFrame(raf);
      }
      resize?.disconnect();
      watch?.disconnect();
      stage.removeEventListener("pointermove", onMove);
      stage.removeEventListener("pointerleave", onLeave);
      stage.removeEventListener("click", onClick);
      stage.removeEventListener("focusin", onFocus);
      stage.removeEventListener("focusout", onBlur);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", request);
      delete stage.dataset.side;
      stage.style.cursor = "";
    },
  };
}
