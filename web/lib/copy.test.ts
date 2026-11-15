import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Rule 1: UI copy never asserts truth. Word list is shared with weft_core.ask (config/banned_words.json).
const WORDS: string[] = JSON.parse(readFileSync(resolve(__dirname, "../../config/banned_words.json"), "utf8")).words;
const ROOT = resolve(__dirname, "..");

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? files(p) : /\.tsx?$/.test(f) && !/\.test\./.test(f) ? [p] : [];
  });
}

/** Text a reader could see: string literals and JSX text. Identifiers like `false` stay out. */
export function copyOf(src: string): string[] {
  const out = [...src.matchAll(/(["'`])((?:\\.|(?!\1).)*)\1/g)].map((m) => m[2]);
  out.push(...[...src.matchAll(/>([^<>{}\n]+)</g)].map((m) => m[1]));
  return out;
}

// "what is true" is how the disclaimers read ("never says what is true"); that is the opposite of a claim.
const hit = (text: string) => {
  const t = text.replace(/\bwhat is (true|untrue)\b/gi, "");
  return WORDS.filter((w) => new RegExp(`\\b${w.replace("-", "[- ]")}\\b`, "i").test(t));
};

// shortcut: a path:word allowlist for the narrow documented senses (a document existing); keep it empty if possible.
const ALLOW = new Set<string>([]);

describe("copy guard", () => {
  it("flags a banned word in copy", () => {
    expect(copyOf('<p>The claim was debunked</p>').flatMap(hit)).toEqual(["debunked"]);
  });
  it("allows the disclaimer form", () => {
    expect(copyOf("<p>Weft never says what is true.</p>").flatMap(hit)).toEqual([]);
  });
  it("ignores code identifiers", () => {
    expect(copyOf("const ok = false; return ok === false;").flatMap(hit)).toEqual([]);
  });
  it("no page or component asserts truth", () => {
    const bad: string[] = [];
    for (const f of [...files(join(ROOT, "app")), ...files(join(ROOT, "components"))]) {
      const rel = f.slice(ROOT.length + 1);
      for (const t of copyOf(readFileSync(f, "utf8"))) for (const w of hit(t)) if (!ALLOW.has(`${rel}:${w}`)) bad.push(`${rel}: "${w}" in ${t.slice(0, 60)}`);
    }
    expect(bad).toEqual([]);
  });
});
