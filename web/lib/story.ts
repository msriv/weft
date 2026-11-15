// Pure helpers for the story page: tab links, conflict pairing, merged claim lists.
import { count } from "@/lib/format";
import type { GraphEdge, GraphNode, ShortVersion, StoryGraph } from "./types";

export const TABS = [["overview", "Overview"], ["timeline", "Timeline"], ["network", "Network"], ["anomalies", "Anomalies"], ["questions", "Questions"]] as const;
export type Tab = (typeof TABS)[number][0];
export type StoryQuery = { tab?: string; view?: string; at?: string; live?: string; until?: string; days?: string; kind?: string };

/** Old `?view=list` links open the Timeline. */
export function tabOf(q: StoryQuery): Tab {
  if (TABS.some(([k]) => k === q.tab)) return q.tab as Tab;
  return q.view === "list" ? "timeline" : "overview";
}

/** A link to `tab` (or with other changes) that keeps replay date, window and live mode. */
export function storyHref(id: string, q: StoryQuery, change: Partial<StoryQuery> = {}): string {
  const keep = { at: q.at, until: q.until, days: q.days, live: q.live, kind: q.kind, tab: tabOf(q) === "overview" ? undefined : tabOf(q) };
  const next = { ...keep, ...change };
  const p = new URLSearchParams(Object.entries(next).filter((e): e is [string, string] => !!e[1] && e[1] !== "overview"));
  return `/s/${id}${p.size ? `?${p}` : ""}`;
}

export type Side = { claim: string; perspectives: string[]; outlets: string[] };
export type Conflict = { event_id: string; a: Side; b: Side };

/** Each "reports conflict on" pair with who carries each side. Sides come from the conflict edges
 * of the same event (perspectives) and the report groups of those perspectives (outlets). */
export function conflicts(sv: ShortVersion, edges: GraphEdge[], nodes: GraphNode[]): Conflict[] {
  const seen = new Map<string, number>();
  return sv.reports_conflict_on.filter((c) => c.labels.length >= 2).map((c) => {
    const n = seen.get(c.event_id) ?? 0;
    seen.set(c.event_id, n + 1);
    const e = edges.filter((x) => x.event_id === c.event_id)[n];
    const side = (i: number): Side => {
      const perspectives = e?.between[i] ?? [];
      const outlets = [...new Set(nodes.filter((x) => x.event_id === c.event_id && x.perspective && perspectives.includes(x.perspective)).flatMap((x) => x.sources ?? []))].sort();
      return { claim: c.labels[i], perspectives, outlets };
    };
    return { event_id: c.event_id, a: side(0), b: side(1) };
  });
}

/** "Carried by every perspective": the short version's claims and the ranked claims merged, one
 * line per claim, each with its coverage note when there is one. */
export function carriedByAll(g: Pick<StoryGraph, "short_version" | "summary_items">): { text: string; coverage: string | null }[] {
  const out = new Map<string, { text: string; coverage: string | null }>();
  for (const x of g.summary_items ?? []) out.set(x.text.trim().toLowerCase(), { text: x.text, coverage: x.coverage });
  for (const x of g.short_version.reported_by_all) if (!out.has(x.label.trim().toLowerCase())) out.set(x.label.trim().toLowerCase(), { text: x.label, coverage: null });
  return [...out.values()];
}

/** The beat id is internal ("kessar-strait"); show it as words. */
export const beatName = (beat: string): string => {
  const t = beat.replace(/[-_]+/g, " ").trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
};

export const plural = count;
