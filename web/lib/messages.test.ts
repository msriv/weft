import { describe, expect, it } from "vitest";
import { askMessage, authMessage, citeNumbers } from "./messages";

describe("authMessage", () => {
  it("maps Firebase codes to sentences, never the raw code", () => {
    for (const raw of ["EMAIL_NOT_FOUND", "INVALID_PASSWORD", "EMAIL_EXISTS", "WEAK_PASSWORD : Password should be at least 6 characters", "TOO_MANY_ATTEMPTS_TRY_LATER", "SOMETHING_NEW"]) {
      const m = authMessage(new Error(raw));
      expect(m).not.toMatch(/[A-Z]{3,}_[A-Z]{3,}/);
      expect(m.endsWith(".")).toBe(true);
    }
    expect(authMessage(new Error("WEAK_PASSWORD : x"))).toContain("6 characters");
  });
});
describe("askMessage", () => {
  it("has a distinct message for the limit and for no network", () => {
    expect(new Set([askMessage(429), askMessage(0), askMessage(500)]).size).toBe(3);
  });
});
describe("citeNumbers", () => {
  it("numbers each source once across the answer", () => {
    const m = citeNumbers([{ cites: ["a", "b"] }, { cites: ["b", "c"] }, { cites: ["a"] }]);
    expect([...m]).toEqual([["a", 1], ["b", 2], ["c", 3]]);
  });
});
