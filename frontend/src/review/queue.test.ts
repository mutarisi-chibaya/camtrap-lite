import { describe, expect, it } from "vitest";
import type { ReviewEvent } from "../api/client";
import {
  type ReviewState,
  eventsPerMinute,
  excludeIds,
  initialState,
  needsRefill,
  reducer,
  reviewDuration,
} from "./queue";

const ev = (id: number, nImages = 2): ReviewEvent => ({
  id,
  camera_id: 1,
  camera_name: "A01",
  start_time: null,
  end_time: null,
  max_animal_conf: 0.5,
  images: Array.from({ length: nImages }, (_, i) => ({
    id: id * 10 + i,
    original_filename: `${id}_${i}.jpg`,
    width: 100,
    height: 80,
    timestamp: null,
    timestamp_source: "missing" as const,
    detections: [],
  })),
});

const loaded = (ids: number[], now = 1000, remaining = 10): ReviewState =>
  reducer(initialState(0), { type: "loaded", events: ids.map((i) => ev(i)), remaining, now });

describe("review queue", () => {
  it("loads events and starts timing when the first one appears", () => {
    const s = loaded([1, 2]);
    expect(s.queue.map((e) => e.id)).toEqual([1, 2]);
    expect(s.shownAt).toBe(1000);
    expect(s.remaining).toBe(10);
  });

  it("ignores duplicates on refill and marks the server exhausted", () => {
    let s = loaded([1, 2]);
    s = reducer(s, { type: "loaded", events: [ev(2), ev(3)], remaining: 10, now: 2000 });
    expect(s.queue.map((e) => e.id)).toEqual([1, 2, 3]);
    expect(s.exhausted).toBe(false);
    expect(s.shownAt).toBe(1000); // current event unchanged, timer not reset
    s = reducer(s, { type: "loaded", events: [ev(3)], remaining: 10, now: 2500 });
    expect(s.exhausted).toBe(true);
  });

  it("decide advances instantly and records the decision", () => {
    let s = loaded([1, 2]);
    expect(reviewDuration(s, 3500)).toBe(2500);
    s = reducer(s, { type: "decide", label: "empty", now: 3500 });
    expect(s.queue.map((e) => e.id)).toEqual([2]);
    expect(s.history).toEqual([{ event: ev(1), label: "empty", decidedAt: 3500 }]);
    expect(s.shownAt).toBe(3500);
    expect(s.remaining).toBe(9);
    expect(s.sessionStart).toBe(1000);
  });

  it("decide on an empty queue is a no-op", () => {
    const s = initialState(0);
    expect(reducer(s, { type: "decide", label: "animal", now: 1 })).toBe(s);
  });

  it("undo puts the last event back in front", () => {
    let s = loaded([1, 2]);
    s = reducer(s, { type: "decide", label: "animal", now: 2000 });
    s = reducer(s, { type: "undo", now: 3000 });
    expect(s.queue.map((e) => e.id)).toEqual([1, 2]);
    expect(s.history).toEqual([]);
    expect(s.remaining).toBe(10);
    expect(reducer(s, { type: "undo", now: 4000 })).toBe(s);
  });

  it("image navigation is clamped to the event", () => {
    let s = loaded([1]);
    s = reducer(s, { type: "image", delta: -1 });
    expect(s.imageIndex).toBe(0);
    s = reducer(reducer(reducer(s, { type: "image", delta: 1 }), { type: "image", delta: 1 }), {
      type: "image",
      delta: 1,
    });
    expect(s.imageIndex).toBe(1);
    s = reducer(s, { type: "decide", label: "animal", now: 5 });
    expect(s.imageIndex).toBe(0);
  });

  it("refills when low and excludes queued + recently decided ids", () => {
    let s = loaded([1, 2, 3]);
    expect(needsRefill(s)).toBe(false);
    s = reducer(s, { type: "decide", label: "animal", now: 2000 });
    expect(needsRefill(s)).toBe(true);
    expect(excludeIds(s).sort()).toEqual([1, 2, 3]);
  });

  it("computes events per minute over the session", () => {
    let s = loaded([1, 2, 3], 0);
    expect(eventsPerMinute(s, 1000)).toBeNull();
    s = reducer(s, { type: "decide", label: "animal", now: 15_000 });
    s = reducer(s, { type: "decide", label: "empty", now: 30_000 });
    expect(eventsPerMinute(s, 30_000)).toBeCloseTo(4);
  });
});
