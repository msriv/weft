import { describe, expect, it } from "vitest";
// @ts-expect-error plain JS config module
import config, { csp } from "../next.config.mjs";

describe("security headers", () => {
  it("sends the headers on every path", async () => {
    const rules = await config.headers();
    expect(rules).toHaveLength(1);
    expect(rules[0].source).toBe("/:path*");
    const h = Object.fromEntries(rules[0].headers.map((x: { key: string; value: string }) => [x.key, x.value]));
    expect(h["X-Frame-Options"]).toBe("DENY");
    expect(h["Referrer-Policy"]).toBe("strict-origin-when-cross-origin");
    expect(h["X-Content-Type-Options"]).toBe("nosniff");
    expect(h["Strict-Transport-Security"]).toMatch(/max-age=\d+/);
    expect(h["Content-Security-Policy"]).toBe(csp);
  });
  it("limits framing, plugins and connections", () => {
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("connect-src 'self'");
  });
});
