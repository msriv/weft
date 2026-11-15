// Claim matrix model: which outlets carry which claim group, in the order a reader needs.
import type { EventPage } from "./types";

export type Col = { key: string; p: string; name: string; ids: Set<string> };
export type Row = {
  id: string; label: string; conflict: boolean; perspectives: string[]; hits: Map<string, { report_id: string; text: string }>;
};
export type Filter = "all" | "conflicts" | "single";

export function columns(e: EventPage): Col[] {
  return Object.entries(e.perspectives).flatMap(([p, reps]) => {
    const by = new Map<string, Set<string>>();
    for (const r of reps) by.set(r.source.name, (by.get(r.source.name) ?? new Set()).add(r.id));
    return [...by.entries()].map(([name, ids]) => ({ key: `${p}:${name}`, p, name, ids }));
  });
}

/** Rows: conflicting groups first with the two sides next to each other, then by how many
 * perspectives carry the claim (most first), then by label. */
export function rows(e: EventPage, cols: Col[]): Row[] {
  const inConflict = new Set(e.conflicts.flatMap((c) => c.groups));
  const made = new Map<string, Row>();
  for (const g of e.claim_groups.filter((x) => x.claims?.length)) {
    const hits = new Map<string, { report_id: string; text: string }>();
    for (const c of cols) {
      const hit = g.claims.find((x) => c.ids.has(x.report_id));
      if (hit) hits.set(c.key, hit);
    }
    const perspectives = [...new Set(cols.filter((c) => hits.has(c.key)).map((c) => c.p))];
    made.set(g.id, { id: g.id, label: g.label, conflict: inConflict.has(g.id), perspectives, hits });
  }
  const out: Row[] = [];
  const put = (r?: Row) => { if (r && !out.includes(r)) out.push(r); };
  for (const c of e.conflicts) for (const id of c.groups) put(made.get(id));
  const rest = [...made.values()].filter((r) => !out.includes(r));
  rest.sort((a, b) => b.perspectives.length - a.perspectives.length || a.label.localeCompare(b.label));
  return [...out, ...rest];
}

export function filterRows(rs: Row[], f: Filter): Row[] {
  if (f === "conflicts") return rs.filter((r) => r.conflict);
  if (f === "single") return rs.filter((r) => r.perspectives.length === 1);
  return rs;
}

/** "3 of 5 perspectives": how many of the perspectives in this event carry the claim. */
export const coverage = (r: Row, total: number): string => `${r.perspectives.length} of ${total} ${total === 1 ? "perspective" : "perspectives"}`;
