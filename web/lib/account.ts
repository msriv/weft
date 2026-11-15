"use client";
// Reader account: Firebase sign-in through /api/auth, preferences synced through /api/v1/me/prefs.
// Guests are untouched: everything still works from localStorage alone.
import type { Prefs } from "./prefs";

type Session = { idToken: string; refreshToken: string; email: string; expiresAt: number };
const KEY = "weft:session";

function load(): Session | null {
  try { return JSON.parse(localStorage.getItem(KEY) ?? "null") as Session | null; } catch { return null; }
}
export const signedInAs = (): string | null => load()?.email ?? null;
/** True once after a refresh failure signed the reader out, so the page can say syncing stopped. */
export function takeLapsed(): boolean {
  const v = localStorage.getItem("weft:lapsed") === "1";
  localStorage.removeItem("weft:lapsed");
  return v;
}
export const signOut = (): void => localStorage.removeItem(KEY);

async function auth(action: string, body: object): Promise<Session> {
  const r = await fetch(`/api/auth/${action}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error ?? "auth failed");
  const s: Session = { idToken: j.idToken, refreshToken: j.refreshToken, email: j.email, expiresAt: Date.now() + j.expiresIn * 1000 - 60_000 };
  localStorage.setItem(KEY, JSON.stringify(s));
  return s;
}
export const signIn = (email: string, password: string, create: boolean) => auth(create ? "signup" : "signin", { email, password });

async function token(): Promise<string | null> {
  let s = load();
  if (!s) return null;
  if (Date.now() > s.expiresAt) {
    try { s = await auth("refresh", { refreshToken: s.refreshToken, email: s.email }); } catch { signOut(); localStorage.setItem("weft:lapsed", "1"); return null; }
  }
  return s.idToken;
}

export async function pullPrefs(): Promise<Partial<Prefs> | null> {
  const t = await token();
  if (!t) return null;
  const r = await fetch("/api/v1/me/prefs", { headers: { authorization: `Bearer ${t}` } });
  return r.ok ? ((await r.json()) as Partial<Prefs>) : null;
}
export async function pushPrefs(p: Prefs): Promise<void> {
  const t = await token();
  if (t) await fetch("/api/v1/me/prefs", { method: "PUT", headers: { "content-type": "application/json", authorization: `Bearer ${t}` }, body: JSON.stringify(p) });
}
