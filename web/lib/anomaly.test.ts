import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { RULES_WITH_TEMPLATE, chips, groupByEvent, kindCounts, sentence } from "./anomaly";
import { RULES } from "./format";

const WORDS: string[] = JSON.parse(readFileSync(resolve(__dirname, "../../config/banned_words.json"), "utf8")).words;
const mk = (rule: string, detail: Record<string, unknown> = {}) => ({ rule, detail, summary: "stored summary" });

describe("sentence", () => {
  it("has a plain template for each of the 12 rules, in coverage language", () => {
    expect(RULES_WITH_TEMPLATE).toHaveLength(12);
    for (const r of RULES_WITH_TEMPLATE) {
      const s = sentence(mk(r, { perspective: "KE", term: "regime" }));
      expect(s, r).not.toBe("stored summary");
      for (const w of WORDS) expect(s, `${r}: ${w}`).not.toMatch(new RegExp(`\\b${w.replace("-", "[- ]")}\\b`, "i"));
    }
    expect(Object.keys(RULES)).toEqual(expect.arrayContaining(RULES_WITH_TEMPLATE));
  });
  it("falls back to the stored summary for an unknown rule", () => expect(sentence(mk("future_rule"))).toBe("stored summary"));
  it("names the perspective for omission and the word for loaded wording", () => {
    expect(sentence(mk("omission", { perspective: "KE" }))).toContain("Kenya");
    expect(sentence(mk("loaded_wording", { term: "regime" }))).toContain("“regime”");
  });
});

describe("lists", () => {
  const a = (id: string, rule: string, event_id: string, since: string) => ({ id, rule, event_id, since });
  const list = [a("1", "silence", "e1", "2026-11-01"), a("2", "numbers_differ", "e2", "2026-11-05"), a("3", "silence", "e2", "2026-11-03")];
  it("groups by event, newest first, and filters by kind", () => {
    expect(groupByEvent(list).map(([e, xs]) => [e, xs.map((x) => x.id)])).toEqual([["e2", ["2", "3"]], ["e1", ["1"]]]);
    expect(groupByEvent(list, "silence").map(([e]) => e)).toEqual(["e2", "e1"]);
  });
  it("counts per kind", () => expect(kindCounts(list)).toEqual([["silence", 2], ["numbers_differ", 1]]));
  it("shows four chips then how many more", () => expect(chips([1, 2, 3, 4, 5, 6, 7])).toEqual({ shown: [1, 2, 3, 4], more: 3 }));
});
