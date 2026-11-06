// Computed story-graph layout (never force-directed): x = day, official documents on a spine in
// the middle, one band per perspective above or below it. The same story always draws the same
// way, so Replay and screenshots stay stable.
import type { GraphEdge, GraphNode } from "./types";

export type Placed = GraphNode & { x: number; y: number; r: number; band: number };
export type Layout = {
  nodes: Placed[]; edges: { from: Placed; to: Placed; event_id: string }[];
  days: { day: string; x: number }[]; bands: { perspective: string; y: number }[];
  spineY: number; width: number; height: number;
};

export const BAND_H = 120;
const PAD = 60;

export function dayOf(n: GraphNode): string {
  return (n.at ?? "").slice(0, 10);
}

/** Bands alternate above and below the spine: first perspective above, second below, and so on. */
export function bandIndex(perspectives: string[], p: string): number {
  const i = perspectives.indexOf(p);
  return (i % 2 === 0 ? -1 : 1) * (Math.floor(i / 2) + 1);
}

export function layout(
  nodes: GraphNode[], edges: GraphEdge[], perspectives: string[], width = 960,
): Layout {
  const days = [...new Set(nodes.map(dayOf).filter(Boolean))].sort();
  const step = days.length > 1 ? (width - 2 * PAD) / (days.length - 1) : 0;
  const xOf = (d: string) => (days.length > 1 ? PAD + days.indexOf(d) * step : width / 2);
  const above = Math.max(0, ...perspectives.map((p) => -bandIndex(perspectives, p)));
  const below = Math.max(0, ...perspectives.map((p) => bandIndex(perspectives, p)));
  const spineY = Math.max(above, 1) * BAND_H;
  const height = spineY + Math.max(below, 1) * BAND_H;
  const slot = new Map<string, number>(); // nodes sharing a day and band stack apart
  const placed: Placed[] = [...nodes]
    .sort((a, b) => (a.at ?? "").localeCompare(b.at ?? "") || a.id.localeCompare(b.id))
    .map((n) => {
      const band = n.kind === "document" ? 0 : bandIndex(perspectives, n.perspective ?? "");
      const key = `${dayOf(n)}|${band}`;
      const k = slot.get(key) ?? 0;
      slot.set(key, k + 1);
      const r = n.kind === "document" ? 9 : Math.min(8 + 4 * Math.sqrt(n.count ?? 1), 34);
      const offset = (band === 0 ? 0 : Math.sign(band) * 34) + (k % 3) * 38 * (band >= 0 ? 1 : -1);
      const y = spineY + band * BAND_H * 0.5 + offset - (band === 0 ? (k % 3) * 0 : 0);
      return { ...n, x: xOf(dayOf(n)) + Math.floor(k / 3) * 14, y, r, band };
    });
  const byId = new Map(placed.map((n) => [n.id, n]));
  const out: Layout["edges"] = [];
  for (const e of edges) {
    const [a, b] = e.between.map((ps) => ps[0]);
    const na = placed.find((n) => n.event_id === e.event_id && n.perspective === a);
    const nb = placed.find((n) => n.event_id === e.event_id && n.perspective === b);
    if (na && nb && na !== nb && byId.has(na.id) && byId.has(nb.id)) out.push({ from: na, to: nb, event_id: e.event_id });
  }
  return {
    nodes: placed, edges: out, days: days.map((d) => ({ day: d, x: xOf(d) })),
    bands: perspectives.map((p) => ({ perspective: p, y: spineY + bandIndex(perspectives, p) * BAND_H * 0.5 })),
    spineY, width, height,
  };
}
