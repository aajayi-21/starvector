/**
 * jsdom stubs for the component project: canvas 2D contexts (jsdom
 * has none — the drawing calls become no-ops), a synchronous
 * ResizeObserver with a fixed 300x300 content box, immediate
 * animation frames, and matchMedia. Real rendering is checked by
 * the Playwright suite and the device matrix, not here.
 */

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Vitest runs without injected globals, so RTL cannot self-register
// its cleanup — do it here or trees accumulate across tests.
afterEach(() => cleanup());

const FAKE_SIZE = { width: 300, height: 300 };

class FakeResizeObserver {
  private readonly callback: ResizeObserverCallback;

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
  }

  observe(target: Element): void {
    const entry = {
      target,
      contentRect: { ...FAKE_SIZE, top: 0, left: 0, x: 0, y: 0 },
      devicePixelContentBoxSize: undefined,
    } as unknown as ResizeObserverEntry;
    this.callback([entry], this as unknown as ResizeObserver);
  }

  unobserve(): void {}
  disconnect(): void {}
}

Object.defineProperty(globalThis, "ResizeObserver", {
  writable: true,
  value: FakeResizeObserver,
});

const contextStub = () =>
  new Proxy(
    {},
    {
      get: (target: Record<string, unknown>, name: string) => {
        if (name in target) {
          return target[name];
        }
        return () => undefined;
      },
      set: (target: Record<string, unknown>, name: string, value: unknown) => {
        target[name] = value;
        return true;
      },
    },
  );

Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
  writable: true,
  value: function getContext() {
    return contextStub();
  },
});

Object.defineProperty(globalThis, "requestAnimationFrame", {
  writable: true,
  value: (callback: FrameRequestCallback): number => {
    callback(0);
    return 0;
  },
});

Object.defineProperty(globalThis, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }),
});

// jsdom 30 ships no Storage implementation — a memory stub matches
// the app's disposable-cache semantics (spec W1 §8).
class MemoryStorage {
  private store = new Map<string, string>();

  get length(): number {
    return this.store.size;
  }

  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  clear(): void {
    this.store.clear();
  }

  key(index: number): string | null {
    return [...this.store.keys()][index] ?? null;
  }
}

Object.defineProperty(window, "localStorage", {
  writable: true,
  value: new MemoryStorage(),
});
