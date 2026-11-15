// Browser smoke test: builds nothing; expects `next build` done. Starts the stub API and the app,
// then checks every page at phone and desktop sizes: no sideways scroll, no console errors,
// no overlapping cards on the story page. Run: npm run e2e
import { spawn } from "node:child_process";
import { chromium } from "playwright";

const PAGES = ["/", "/today", "/stories", "/sources", "/s/kessar-strait", "/s/kessar-strait?tab=timeline", "/s/kessar-strait?tab=network", "/s/kessar-strait?tab=anomalies", "/s/kessar-strait?tab=questions", "/s/kessar-strait/e/e1", "/s/busy?tab=network", "/ask", "/welcome", "/method"];
const procs = [
  spawn("node", ["e2e/stub-api.mjs", "8099"], { stdio: "inherit" }),
  spawn("node", ["node_modules/next/dist/bin/next", "start", "-p", "3099"], { stdio: "inherit", env: { ...process.env, API_URL: "http://localhost:8099" } }),
];
const stop = () => procs.forEach((p) => p.kill());
process.on("exit", stop);

const up = async () => { for (let i = 0; i < 60; i++) { try { if ((await fetch("http://localhost:3099/")).ok) return; } catch {} await new Promise((r) => setTimeout(r, 500)); } throw new Error("app did not start"); };
await up();

const bad = [];
const b = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
for (const [w, h] of [[390, 844], [1280, 900]]) {
  const p = await (await b.newContext({ viewport: { width: w, height: h } })).newPage();
  const errs = [];
  p.on("console", (m) => m.type() === "error" && errs.push(m.text()));
  p.on("pageerror", (e) => errs.push(String(e)));
  for (const path of PAGES) {
    errs.length = 0;
    await p.goto(`http://localhost:3099${path}`, { waitUntil: "networkidle" });
    const [sw, cw] = await p.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    if (sw !== cw) bad.push(`${w}px ${path}: scrollWidth ${sw} != clientWidth ${cw}`);
    const own = errs.filter((e) => !/favicon|Failed to load resource/.test(e));
    if (own.length) bad.push(`${w}px ${path}: console errors ${own.join(" | ").slice(0, 200)}`);
    const text = await p.evaluate(() => document.body.innerText);
    for (const [re, what] of [[/\d{4}-\d{2}-\d{2}/, "ISO date"], [/\b(AL|VE|KE)\b/, "country code"], [/kessar-strait/i, "beat id"]]) {
      const m = text.match(re);
      if (m) bad.push(`${w}px ${path}: visible ${what} "${m[0]}"`);
    }
    if (path === "/s/kessar-strait") {
      const boxes = await p.$$eval(".card", (els) => els.filter((e) => e.offsetParent).map((e) => { const r = e.getBoundingClientRect(); return [r.left, r.top + scrollY, r.right, r.bottom + scrollY]; }));
      for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
        const [a, c] = [boxes[i], boxes[j]];
        if (a[0] < c[2] - 1 && c[0] < a[2] - 1 && a[1] < c[3] - 1 && c[1] < a[3] - 1) bad.push(`${w}px ${path}: cards ${i} and ${j} overlap`);
      }
    }
  }
}
await b.close();
stop();
if (bad.length) { console.error(bad.join("\n")); process.exit(1); }
console.log(`ok: ${PAGES.length} pages at 2 sizes`);
