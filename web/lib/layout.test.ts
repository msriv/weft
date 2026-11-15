import { describe, expect, it } from "vitest";
import { bandIndex, layout, type Placed } from "./layout";
import type { GraphNode } from "./types";

const g = (id: string, p: string, at: string, count = 3, event = "e"): GraphNode => ({
  id, kind: "report_group", event_id: event, at, anomalies: [], perspective: p, count,
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
  it("alternates perspective lanes around the document spine", () => {
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

describe("layout of a busy story", () => {
  // 70 groups, 5 fictional perspectives, 7 days, uneven sizes, some days piled up
  const P = ["AA", "BB", "CC", "DD", "EE"];
  const nodes: GraphNode[] = Array.from({ length: 70 }, (_, i) =>
    g(`n${String(i).padStart(2, "0")}`, P[(i * 7) % 5], `2026-11-${String(8 + ((i * 3) % 7)).padStart(2, "0")}T0${i % 9}:00`, 1 + ((i * 13) % 40), `e${i % 6}`));
  const L = layout(nodes, [], P);
  const hit = (a: Placed, b: Placed) => Math.hypot(a.x - b.x, a.y - b.y) < a.r + b.r;

  it("places every node and no two circles intersect", () => {
    expect(L.nodes).toHaveLength(70);
    for (let i = 0; i < L.nodes.length; i++) for (let j = i + 1; j < L.nodes.length; j++) {
      expect(hit(L.nodes[i], L.nodes[j]), `${L.nodes[i].id} and ${L.nodes[j].id}`).toBe(false);
    }
  });
  it("keeps every node, ring included, inside the viewBox", () => {
    for (const n of L.nodes) {
      expect(n.x - n.r - 6).toBeGreaterThanOrEqual(L.gutter);
      expect(n.x + n.r + 6).toBeLessThanOrEqual(L.width);
      expect(n.y - n.r - 6).toBeGreaterThanOrEqual(0);
      expect(n.y + n.r + 6).toBeLessThanOrEqual(L.height);
    }
  });
  it("gives each lane its own band of height and keeps its nodes inside it", () => {
    for (let i = 1; i < L.lanes.length; i++) expect(L.lanes[i].top).toBeGreaterThanOrEqual(L.lanes[i - 1].bottom);
    for (const n of L.nodes) {
      const lane = L.lanes.find((l) => l.band === n.band)!;
      expect(n.y - n.r).toBeGreaterThanOrEqual(lane.top);
      expect(n.y + n.r).toBeLessThanOrEqual(lane.bottom);
    }
  });
  it("keeps names in the gutter, clear of every node", () => {
    for (const n of L.nodes) expect(n.x - n.r).toBeGreaterThan(L.gutter - 1);
  });
});
