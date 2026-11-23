import { describe, expect, it } from "vitest";
import { boxStyle, cropStyle } from "./boxes";

describe("boxStyle", () => {
  it("converts normalised xywh to percentages", () => {
    const s = boxStyle([0.1, 0.2, 0.3, 0.4]);
    const pct = (v: unknown) => parseFloat(String(v));
    expect(pct(s.left)).toBeCloseTo(10);
    expect(pct(s.top)).toBeCloseTo(20);
    expect(pct(s.width)).toBeCloseTo(30);
    expect(pct(s.height)).toBeCloseTo(40);
    expect(String(s.width).endsWith("%")).toBe(true);
  });

  it("clips boxes that extend past the image edge", () => {
    const s = boxStyle([0.9, -0.1, 0.3, 0.5]);
    expect(s.left).toBe("90%");
    expect(s.top).toBe("0%");
    expect(parseFloat(String(s.width))).toBeCloseTo(10);
    expect(parseFloat(String(s.height))).toBeCloseTo(40);
  });
});

describe("cropStyle", () => {
  const num = (v: unknown) => parseFloat(String(v));

  it("does not zoom large boxes", () => {
    const s = cropStyle([0.0, 0.0, 0.9, 0.94]);
    expect(num(s.width)).toBeCloseTo(100);
    expect(num(s.left)).toBeCloseTo(0);
  });

  it("zooms and centres a small box", () => {
    const s = cropStyle([0.45, 0.45, 0.1, 0.1]); // centre 0.5, zoom 5
    expect(num(s.width)).toBeCloseTo(500);
    expect(num(s.left)).toBeCloseTo(-200); // 0.5 - 0.5 * 5 = -2
  });

  it("never shows past the image edge", () => {
    const s = cropStyle([0.0, 0.95, 0.05, 0.05]); // corner box, zoom 6 (capped)
    expect(num(s.width)).toBeCloseTo(600);
    expect(num(s.left)).toBeCloseTo(0);
    expect(num(s.top)).toBeCloseTo(-500); // 1 - zoom
  });
});
