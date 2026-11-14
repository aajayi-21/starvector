/**
 * Drafts on this device (spec W1 §8, spec PL1 §4 and §8). They are
 * disposable caches: a failed read gives nothing and a failed write is
 * dropped. A daily draft is keyed by the day it was drawn for, so a
 * sketch from a day that has closed comes back with its day named.
 */

import type { SketchDoc } from "../sketch/core";

export interface Draft {
  doc: SketchDoc;
  impressions: string[];
  pastedText: string;
  nextStrokeId: number;
  /** The word typed and not yet added. */
  typedWord?: string;
}

export interface PracticeDraft {
  day: string;
  doc: SketchDoc;
  impressions: string[];
  nextStrokeId: number;
  typedWord?: string;
}

const DRAFT_PREFIX = "sv:draft:";
const PRACTICE_KEY = "sv:practice-draft";

export const draftKey = (day: string): string => `${DRAFT_PREFIX}${day}`;
export const sentKey = (day: string): string => `sv:sent:${day}`;

function readJson<T>(key: string): T | null {
  try {
    const raw = window.localStorage.getItem(key);
    return raw === null ? null : (JSON.parse(raw) as T);
  } catch {
    return null;
  }
}

export function writeStorage(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage full or blocked: the draft note simply stays quiet.
  }
}

export function removeStorage(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Disposable cache.
  }
}

export function readDraft(day: string): Draft | null {
  return readJson<Draft>(draftKey(day));
}

export function hasContent(draft: {
  doc: SketchDoc;
  impressions: ReadonlyArray<string>;
  pastedText?: string;
  typedWord?: string;
}): boolean {
  return (
    draft.doc.strokes.length > 0 ||
    draft.impressions.length > 0 ||
    (draft.pastedText ?? "").trim() !== "" ||
    (draft.typedWord ?? "").trim() !== ""
  );
}

function draftDays(): string[] {
  try {
    const days: string[] = [];
    for (let at = 0; at < window.localStorage.length; at += 1) {
      const key = window.localStorage.key(at);
      if (key?.startsWith(DRAFT_PREFIX)) {
        days.push(key.slice(DRAFT_PREFIX.length));
      }
    }
    return days;
  } catch {
    return [];
  }
}

/** True when this device holds an unsent daily draft with content. */
export function hasUnsentDraft(): boolean {
  return draftDays().some((day) => {
    const draft = readDraft(day);
    return draft !== null && hasContent(draft);
  });
}

/** The newest draft with content from a day before this one. */
export function findEarlierDraft(
  day: string,
): { day: string; draft: Draft } | null {
  const earlier = draftDays()
    .filter((label) => label < day)
    .sort()
    .reverse();
  for (const label of earlier) {
    const draft = readDraft(label);
    if (draft !== null && hasContent(draft)) {
      return { day: label, draft };
    }
  }
  return null;
}

/** Remove each draft from a day before this one. */
export function removeEarlierDrafts(day: string): void {
  for (const label of draftDays()) {
    if (label < day) {
      removeStorage(draftKey(label));
    }
  }
}

export function readPracticeDraft(): PracticeDraft | null {
  return readJson<PracticeDraft>(PRACTICE_KEY);
}

export function writePracticeDraft(draft: PracticeDraft): void {
  writeStorage(PRACTICE_KEY, draft);
}

export function clearPracticeDraft(): void {
  removeStorage(PRACTICE_KEY);
}
