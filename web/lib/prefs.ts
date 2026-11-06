"use client";
// Reader preferences. Guests keep them in this browser; signed-in readers also sync to Firestore
// through the API (see lib/account.ts). Nothing here is tracked.
export type Prefs = { regions: string[]; topics: string[]; follows: string[]; frequency: "daily" | "weekly" | "never"; email?: string };
const KEY = "weft:prefs";
export const DEFAULTS: Prefs = { regions: [], topics: [], follows: [], frequency: "daily" };

export function loadPrefs(): Prefs {
  try { return { ...DEFAULTS, ...(JSON.parse(localStorage.getItem(KEY) ?? "{}") as Partial<Prefs>) }; }
  catch { return DEFAULTS; }
}
export function savePrefs(p: Prefs): void { localStorage.setItem(KEY, JSON.stringify(p)); }
