/**
 * Pure state for the Review page, kept separate from React so it can be unit-tested.
 *
 * Decisions are applied locally first (the next event appears instantly) and sent to the
 * API in the background. The queue is refilled from the server when it runs low; ids that
 * are queued, or decided but maybe not yet saved, are excluded from refill requests.
 */

import type { Label, ReviewEvent } from "../api/client";

export interface Decision {
  event: ReviewEvent;
  label: Label;
  decidedAt: number; // ms timestamp
}

export interface ReviewState {
  queue: ReviewEvent[]; // queue[0] is the event on screen
  history: Decision[]; // most recent last
  imageIndex: number; // which image of the current event is shown large
  shownAt: number; // when queue[0] was first shown, for review_duration_ms
  sessionStart: number | null; // first decision of this session
  remaining: number | null; // server count of events still needing review
  exhausted: boolean; // server returned nothing new on the last refill
}

export type Action =
  | { type: "loaded"; events: ReviewEvent[]; remaining: number; now: number }
  | { type: "decide"; label: Label; now: number }
  | { type: "undo"; now: number }
  | { type: "image"; delta: number }
  | { type: "remaining"; remaining: number };

export const REFILL_BELOW = 3;
export const PREFETCH = 5;

export function initialState(now: number): ReviewState {
  return {
    queue: [],
    history: [],
    imageIndex: 0,
    shownAt: now,
    sessionStart: null,
    remaining: null,
    exhausted: false,
  };
}

export function reducer(state: ReviewState, action: Action): ReviewState {
  switch (action.type) {
    case "loaded": {
      const known = new Set([...state.queue, ...state.history.map((d) => d.event)].map((e) => e.id));
      const fresh = action.events.filter((e) => !known.has(e.id));
      const wasEmpty = state.queue.length === 0;
      return {
        ...state,
        queue: [...state.queue, ...fresh],
        remaining: action.remaining,
        exhausted: fresh.length === 0,
        shownAt: wasEmpty && fresh.length ? action.now : state.shownAt,
        imageIndex: wasEmpty ? 0 : state.imageIndex,
      };
    }
    case "decide": {
      const [current, ...rest] = state.queue;
      if (!current) return state;
      return {
        ...state,
        queue: rest,
        history: [...state.history, { event: current, label: action.label, decidedAt: action.now }],
        imageIndex: 0,
        shownAt: action.now,
        sessionStart: state.sessionStart ?? state.shownAt,
        remaining: state.remaining === null ? null : Math.max(0, state.remaining - 1),
      };
    }
    case "undo": {
      const last = state.history[state.history.length - 1];
      if (!last) return state;
      return {
        ...state,
        queue: [last.event, ...state.queue],
        history: state.history.slice(0, -1),
        imageIndex: 0,
        shownAt: action.now,
        remaining: state.remaining === null ? null : state.remaining + 1,
        exhausted: false,
      };
    }
    case "image": {
      const n = state.queue[0]?.images.length ?? 0;
      if (n === 0) return state;
      return { ...state, imageIndex: Math.min(n - 1, Math.max(0, state.imageIndex + action.delta)) };
    }
    case "remaining":
      return { ...state, remaining: action.remaining };
  }
}

/** Duration to record for the event currently on screen. */
export function reviewDuration(state: ReviewState, now: number): number {
  return Math.max(0, Math.round(now - state.shownAt));
}

export function needsRefill(state: ReviewState): boolean {
  return state.queue.length < REFILL_BELOW && !state.exhausted;
}

/** Ids the server must not return again: queued, plus recent decisions that may be in flight. */
export function excludeIds(state: ReviewState): number[] {
  return [...state.queue, ...state.history.slice(-20).map((d) => d.event)].map((e) => e.id);
}

/** Events reviewed per minute this session (null until there are two data points). */
export function eventsPerMinute(state: ReviewState, now: number): number | null {
  if (state.sessionStart === null || state.history.length === 0) return null;
  const minutes = (now - state.sessionStart) / 60_000;
  return minutes > 0 ? state.history.length / minutes : null;
}

export const KEY_LABELS: Record<string, Label> = {
  "1": "animal",
  "2": "empty",
  "3": "person",
  "4": "vehicle",
};
