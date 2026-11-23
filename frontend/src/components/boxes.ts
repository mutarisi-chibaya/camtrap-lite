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

/**
 * Zoom so the box fills about half of the crop, centred on the box but never showing
 * past the image edge. Returns the inner layer's position/size relative to the crop frame
 * (which has the same aspect ratio as the image).
 */
export function cropStyle(bbox: [number, number, number, number], maxZoom = 6): CSSProperties {
  const [x, y, w, h] = bbox;
  const zoom = Math.min(maxZoom, Math.max(1, 0.5 / Math.max(w, h, 1e-6)));
  const cx = x + w / 2;
  const cy = y + h / 2;
  const offset = (c: number) => Math.min(0, Math.max(1 - zoom, 0.5 - c * zoom));
  return {
    width: `${zoom * 100}%`,
    height: `${zoom * 100}%`,
    left: `${offset(cx) * 100}%`,
    top: `${offset(cy) * 100}%`,
  };
}
