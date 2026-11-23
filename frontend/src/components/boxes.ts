import type { CSSProperties } from "react";

/** Normalised MegaDetector bbox [x, y, w, h] (top-left origin) -> CSS percentages. */
export function boxStyle(bbox: [number, number, number, number]): CSSProperties {
  const clamp = (v: number) => Math.min(1, Math.max(0, v));
  const [x, y, w, h] = bbox;
  const left = clamp(x);
  const top = clamp(y);
  return {
    left: `${left * 100}%`,
    top: `${top * 100}%`,
    width: `${(clamp(x + w) - left) * 100}%`,
    height: `${(clamp(y + h) - top) * 100}%`,
  };
}
