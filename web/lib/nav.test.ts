import { describe, expect, it } from "vitest";
import { SECTIONS, sectionOf } from "./nav";

describe("current section", () => {
  const cases: [string, string | null][] = [
    ["/", "/"], ["/world", "/"], ["/today", "/today"], ["/stories", "/stories"],
    ["/s/kessar-strait", "/stories"], ["/s/kessar-strait/e/e1", "/stories"], ["/d/doc1", "/stories"], ["/nodes/r1", "/stories"], ["/people/a", "/stories"],
    ["/sources", "/sources"], ["/sources/aldoria-post", "/sources"], ["/ask", "/ask"],
    ["/method", null], ["/welcome", null],
  ];
  it.each(cases)("%s belongs to %s", (path, section) => expect(sectionOf(path)).toBe(section));
  it("has one entry per header link", () => expect(new Set(SECTIONS.map((s) => s.href)).size).toBe(SECTIONS.length));
});
