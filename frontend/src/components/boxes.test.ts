import { describe, expect, it } from "vitest";
import { boxStyle } from "./boxes";

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
