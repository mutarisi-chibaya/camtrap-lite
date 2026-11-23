import { describe, expect, it } from "vitest";
import { type Point, closesPolygon, isMasked, pointInPolygon, svgPoints, toNormalized } from "./geometry";

const SQUARE: Point[] = [
  [0, 0.6],
  [1, 0.6],
  [1, 1],
  [0, 1],
];

describe("mask geometry", () => {
  it("normalises and clamps clicks to the element", () => {
    const rect = { left: 100, top: 50, width: 200, height: 100 };
    expect(toNormalized(200, 100, rect)).toEqual([0.5, 0.5]);
    expect(toNormalized(50, 400, rect)).toEqual([0, 1]);
  });

  it("matches the backend point-in-polygon rule", () => {
    expect(pointInPolygon([0.5, 0.8], SQUARE)).toBe(true);
    expect(pointInPolygon([0.5, 0.5], SQUARE)).toBe(false);
    const u: Point[] = [
      [0, 0],
      [0.3, 0],
      [0.3, 0.6],
      [0.7, 0.6],
      [0.7, 0],
      [1, 0],
      [1, 1],
      [0, 1],
    ];
    expect(pointInPolygon([0.5, 0.3], u)).toBe(false);
    expect(pointInPolygon([0.1, 0.3], u)).toBe(true);
  });

  it("masks by box centre", () => {
    expect(isMasked([0.4, 0.75, 0.1, 0.08], [SQUARE])).toBe(true);
    expect(isMasked([0.4, 0.2, 0.2, 0.3], [SQUARE])).toBe(false);
    expect(isMasked([0.4, 0.75, 0.1, 0.08], [[[0, 0], [1, 1]]])).toBe(false); // not a polygon
  });

  it("closes the polygon near the first point", () => {
    expect(closesPolygon([0.005, 0.605], SQUARE)).toBe(true);
    expect(closesPolygon([0.5, 0.5], SQUARE)).toBe(false);
    expect(closesPolygon([0, 0.6], SQUARE.slice(0, 2))).toBe(false);
    expect(svgPoints(SQUARE.slice(0, 2))).toBe("0,0.6 1,0.6");
  });
});
