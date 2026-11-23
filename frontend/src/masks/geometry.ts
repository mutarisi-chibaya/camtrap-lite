/** Polygon helpers for the mask editor. Mirrors backend/app/services/masks.py. */

export type Point = [number, number]; // normalised 0-1, origin top-left
export type BBox = [number, number, number, number];

/** Mouse position relative to an element's box, normalised to 0-1 and clamped. */
export function toNormalized(
  clientX: number,
  clientY: number,
  rect: { left: number; top: number; width: number; height: number },
): Point {
  const clamp = (v: number) => Math.min(1, Math.max(0, v));
  return [clamp((clientX - rect.left) / rect.width), clamp((clientY - rect.top) / rect.height)];
}

/** Ray casting, same rule as the backend. */
export function pointInPolygon([x, y]: Point, polygon: Point[]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [x1, y1] = polygon[i];
    const [x2, y2] = polygon[j];
    if (y1 > y !== y2 > y && x < x1 + ((y - y1) * (x2 - x1)) / (y2 - y1)) inside = !inside;
  }
  return inside;
}

/** A detection is masked when its box centre lies inside any polygon. */
export function isMasked([x, y, w, h]: BBox, polygons: Point[][]): boolean {
  const centre: Point = [x + w / 2, y + h / 2];
  return polygons.some((p) => p.length >= 3 && pointInPolygon(centre, p));
}

/** SVG `points` attribute for a viewBox of 0 0 1 1. */
export const svgPoints = (polygon: Point[]) => polygon.map(([x, y]) => `${x},${y}`).join(" ");

/** True if `p` is close enough to the first point to close the polygon. */
export function closesPolygon(p: Point, polygon: Point[], tolerance = 0.015): boolean {
  if (polygon.length < 3) return false;
  const [fx, fy] = polygon[0];
  return Math.hypot(p[0] - fx, p[1] - fy) <= tolerance;
}
