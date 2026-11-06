import { describe, expect, it } from "vitest";
import { bandIndex, layout } from "./layout";
import type { GraphNode } from "./types";

const g = (id: string, p: string, at: string, count = 3): GraphNode => ({
  id, kind: "report_group", event_id: "e", at, anomalies: [], perspective: p, count,
});

describe("layout", () => {
  const nodes = [g("a", "IL", "2026-11-06T01:00"), g("b", "IR", "2026-11-07T01:00"), {
    id: "d", kind: "document" as const, event_id: "e", at: "2026-11-06T09:00", anomalies: [],
  }];
  it("is deterministic and puts x = day", () => {
    const one = layout(nodes, [], ["IL", "IR"]);
    expect(layout([...nodes].reverse(), [], ["IL", "IR"])).toEqual(one);
    const [a, b] = ["a", "b"].map((id) => one.nodes.find((n) => n.id === id)!);
    expect(b.x).toBeGreaterThan(a.x);
  });
  it("alternates perspective bands around the document spine", () => {
    expect([0, 1, 2, 3].map((i) => bandIndex(["a", "b", "c", "d"], ["a", "b", "c", "d"][i]))).toEqual([-1, 1, -2, 2]);
    const l = layout(nodes, [], ["IL", "IR"]);
    expect(l.nodes.find((n) => n.id === "a")!.y).toBeLessThan(l.spineY);
    expect(l.nodes.find((n) => n.id === "b")!.y).toBeGreaterThan(l.spineY);
    expect(l.nodes.find((n) => n.id === "d")!.y).toBe(l.spineY);
  });
  it("links conflicting perspectives of one event", () => {
    const l = layout(nodes, [{ kind: "conflict", event_id: "e", groups: ["x", "y"], between: [["IL"], ["IR"]], nli_score: 0.9 }], ["IL", "IR"]);
    expect(l.edges).toHaveLength(1);
  });
});
