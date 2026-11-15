import { describe, expect, it } from "vitest";
import { radius, spread } from "./globe";

describe("spread", () => {
  const near = (key: string, i: number) => ({ key, x: 200 + i * 2, y: 200 + (i % 2), r: 8 });
  const pts = ["a", "b", "c", "d", "e"].map(near);
  it("separates five markers in neighbouring countries", () => {
    const out = spread(pts);
    for (let i = 0; i < out.length; i++) for (let j = i + 1; j < out.length; j++) {
      expect(Math.hypot(out[i].px - out[j].px, out[i].py - out[j].py)).toBeGreaterThanOrEqual(out[i].r + out[j].r);
    }
  });
  it("fans out two stories on exactly the same point", () => {
    const [a, b] = spread([{ key: "a", x: 50, y: 50, r: 8 }, { key: "b", x: 50, y: 50, r: 8 }]);
    expect(a.moved).toBe(false);
    expect(b.moved).toBe(true);
  });
  it("is deterministic and leaves lone markers where they are", () => {
    expect(spread(pts)).toEqual(spread([...pts].reverse()));
    expect(spread([{ key: "z", x: 1, y: 2, r: 5 }])[0]).toMatchObject({ px: 1, py: 2, moved: false });
  });
  it("caps the radius relative to the globe", () => {
    expect(radius(100000, 560)).toBeCloseTo(11.2);
    expect(radius(1, 560)).toBeGreaterThanOrEqual(4);
  });
});
