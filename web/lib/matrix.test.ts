import { describe, expect, it } from "vitest";
import { columns, coverage, filterRows, rows } from "./matrix";
import { plural } from "./story";
import type { EventPage } from "./types";

// Fictional outlets and places only.
const rep = (id: string, name: string) => ({ id, source: { name } });
const claim = (report_id: string) => ({ report_id, text: "t", start: 0, end: 1 });
const e = {
  perspectives: { AL: [rep("r1", "Aldoria Daily"), rep("r2", "Aldoria Wire")], VE: [rep("r3", "Veymar Wire")], KE: [rep("r4", "Kessar Review")] },
  claim_groups: [
    { id: "solo", label: "Only Kessar says this", perspectives: ["KE"], n_reports: 1, claims: [claim("r4")] },
    { id: "all", label: "Talks announced", perspectives: ["AL", "VE", "KE"], n_reports: 3, claims: [claim("r1"), claim("r3"), claim("r4")] },
    { id: "b", label: "Nine vessels", perspectives: ["VE"], n_reports: 1, claims: [claim("r3")] },
    { id: "a", label: "Twelve vessels", perspectives: ["AL"], n_reports: 2, claims: [claim("r1"), claim("r2")] },
  ],
  conflicts: [{ groups: ["a", "b"], nli_score: 0.9 }],
  figures: [],
} as unknown as EventPage;

describe("claim matrix rows", () => {
  const cols = columns(e);
  const rs = rows(e, cols);
  it("puts conflicting groups first, next to each other, then by perspectives carrying", () => {
    expect(rs.map((r) => r.id)).toEqual(["a", "b", "all", "solo"]);
    expect(rs.filter((r) => r.conflict).map((r) => r.id)).toEqual(["a", "b"]);
  });
  it("filters to conflicts or to one perspective only", () => {
    expect(filterRows(rs, "conflicts").map((r) => r.id)).toEqual(["a", "b"]);
    expect(filterRows(rs, "single").map((r) => r.id)).toEqual(["a", "b", "solo"]);
    expect(filterRows(rs, "all")).toHaveLength(4);
  });
  it("words the per-row coverage with the right plural", () => {
    expect(coverage(rs.find((r) => r.id === "all")!, 3)).toBe("3 of 3 perspectives");
    expect(coverage(rs.find((r) => r.id === "a")!, 1)).toBe("1 of 1 perspective");
  });
  it("uses the right plural for counts", () => {
    expect(plural(1, "report")).toBe("1 report");
  });
});
