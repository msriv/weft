import { describe, expect, it } from "vitest";
import { beatName, carriedByAll, conflicts, plural, storyHref, tabOf } from "./story";
import type { GraphEdge, GraphNode, ShortVersion } from "./types";

describe("tabs", () => {
  it("opens the overview by default and honours ?tab", () => {
    expect(tabOf({})).toBe("overview");
    expect(tabOf({ tab: "network" })).toBe("network");
    expect(tabOf({ tab: "nonsense" })).toBe("overview");
  });
  it("opens the timeline for old ?view=list links", () => {
    expect(tabOf({ view: "list" })).toBe("timeline");
  });
  it("keeps replay date, window and live mode when switching tabs", () => {
    const q = { at: "2026-11-10", until: "2026-11-12", days: "3", live: "1", tab: "network" };
    const href = storyHref("s1", q, { tab: "anomalies" });
    const p = new URL(href, "http://x").searchParams;
    expect([p.get("at"), p.get("until"), p.get("days"), p.get("live"), p.get("tab")]).toEqual(["2026-11-10", "2026-11-12", "3", "1", "anomalies"]);
  });
  it("drops a parameter set to empty, and omits the tab for the overview", () => {
    expect(storyHref("s1", { live: "1" }, { live: "" })).toBe("/s/s1");
    expect(storyHref("s1", { tab: "network" }, { tab: "overview" })).toBe("/s/s1");
  });
});

describe("conflicts", () => {
  const sv = { reports_conflict_on: [{ event_id: "e1", labels: ["Twelve vessels", "Nine vessels"] }], reported_by_all: [], one_perspective_only: [], no_source_published: [] } as ShortVersion;
  const edges = [{ kind: "conflict", event_id: "e1", groups: ["g1", "g2"], between: [["AL"], ["VE"]], nli_score: 0.9 }] as GraphEdge[];
  const nodes = [
    { id: "n1", kind: "report_group", event_id: "e1", perspective: "AL", sources: ["The Aldoria Post"], anomalies: [], at: null },
    { id: "n2", kind: "report_group", event_id: "e1", perspective: "VE", sources: ["Veymar Wire"], anomalies: [], at: null },
  ] as GraphNode[];
  it("names the perspectives and outlets on each side", () => {
    const [c] = conflicts(sv, edges, nodes);
    expect(c.a).toEqual({ claim: "Twelve vessels", perspectives: ["AL"], outlets: ["The Aldoria Post"] });
    expect(c.b.outlets).toEqual(["Veymar Wire"]);
  });
  it("still lists a conflict whose edge is missing", () => {
    expect(conflicts(sv, [], nodes)[0].a.perspectives).toEqual([]);
  });
});

describe("copy helpers", () => {
  it("merges the two claim lists without repeating a sentence", () => {
    const out = carriedByAll({
      short_version: { reported_by_all: [{ event_id: "e", label: "Talks were announced" }, { event_id: "e", label: "Ports reopened" }] } as ShortVersion,
      summary_items: [{ kind: "k", text: "talks were announced", coverage: "14 independent texts, 4 perspectives", groups: [] }],
    });
    expect(out.map((x) => x.text.toLowerCase())).toEqual(["talks were announced", "ports reopened"]);
    expect(out[0].coverage).toContain("14 independent texts");
  });
  it("uses the right plural", () => {
    expect([plural(1, "report"), plural(2, "report"), plural(1, "anomaly", "anomalies"), plural(0, "anomaly", "anomalies")]).toEqual(["1 report", "2 reports", "1 anomaly", "0 anomalies"]);
  });
  it("turns a beat id into words", () => {
    expect(beatName("kessar-strait")).toBe("Kessar strait");
  });
});
