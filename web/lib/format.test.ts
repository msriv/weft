import { describe, expect, it } from "vitest";
import { count, date, dateShort, perspectiveLabel, ruleName, ruleRows, time } from "./format";

describe("count", () => {
  it("handles plurals and separators", () => {
    expect(count(0, "report")).toBe("0 reports");
    expect(count(1, "report")).toBe("1 report");
    expect(count(2, "report")).toBe("2 reports");
    expect(count(1, "anomaly", "anomalies")).toBe("1 anomaly");
    expect(count(1200, "report")).toBe("1,200 reports");
  });
});

describe("dates", () => {
  it("writes words, in UTC", () => {
    expect(date("2026-11-14T23:30:00Z")).toBe("14 Nov 2026");
    expect(date("2026-11-14")).toBe("14 Nov 2026");
    expect(dateShort("2026-11-14T01:00:00Z")).toBe("14 Nov");
    expect(time("2026-11-14T09:05:00Z")).toBe("14 Nov 2026, 09:05 UTC");
    expect(date(null)).toBe("");
  });
});

describe("perspectiveLabel", () => {
  it("uses short country names, words for groups, never a bare code", () => {
    expect(perspectiveLabel("US")).toBe("United States");
    expect(perspectiveLabel("GB")).toBe("United Kingdom");
    expect(perspectiveLabel("IN")).toBe("India");
    expect(perspectiveLabel("unattributed")).toBe("No country recorded");
    expect(perspectiveLabel("gulf-outlets")).toBe("Gulf outlets");
    expect(perspectiveLabel("ZZ")).toBe("Unknown country");
  });
});

describe("rules", () => {
  it("names rules and labels thresholds without JSON", () => {
    expect(ruleName("numbers_differ")).toBe("Numbers differ");
    expect(ruleName("new_rule")).toBe("New rule");
    const rows = ruleRows("numbers_differ", { enabled: true, min_log_ratio: 0.22, max_hours_apart: 6 });
    expect(rows).toEqual([["Smallest gap between figures (log ratio)", "0.22"], ["Most hours between the two reports", "6"]]);
    expect(ruleRows("silent_edit", { refetch_after: ["1h", "24h"] })[0][1]).toBe("1h, 24h");
  });
});
