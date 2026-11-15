import { describe, expect, it } from "vitest";
import { meta } from "./meta";

describe("meta", () => {
  it("gives different titles to different stories", () => {
    expect(meta("Story A", "x").title).not.toEqual(meta("Story B", "x").title);
  });
  it("uses coverage language, never a truth claim", () => {
    const d = String(meta("T", "Coverage of this story.").description).toLowerCase();
    expect(d).toContain("does not say what is true");
    for (const w of ["confirmed", "debunked", "false"]) expect(d).not.toContain(w);
  });
});
