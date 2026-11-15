// Computed story-graph layout (never force-directed): x = day, official documents on a spine in
// the middle, one lane per perspective above or below it. The same story always draws the same
// way, so Replay and screenshots stay stable.
//
// Lanes never overlap: each lane is as tall as its fullest day needs. Inside a day and lane the
// nodes sit side by side and wrap to a new row when the day column is full, so no two circles
// intersect. The size of the drawing comes from where the nodes ended up.
import type { GraphEdge, GraphNode } from "./types";

export type Placed = GraphNode & { x: number; y: number; r: number; band: number };
export type Lane = { perspective: string | null; band: number; top: number; bottom: number; mid: number };
export type Layout = {
  nodes: Placed[]; edges: { from: Placed; to: Placed; event_id: string }[];
  days: { day: string; x: number }[]; lanes: Lane[];
  /** Same as `lanes`, one entry per perspective, with the lane's centre line. */
  bands: { perspective: string; y: number }[];
  spineY: number; width: number; height: number; gutter: number;
};

const GUTTER = 150; // left column for perspective names, outside the plot
const DAY_MIN = 100; // narrowest day column
const GAP = 14; // clear space between node footprints (ring included)
const RING = 6; // anomaly ring sticks out this far
const LANE_PAD = 14;
const AXIS = 30;
const R_MAX = 24;

export function dayOf(n: GraphNode): string {
  return (n.at ?? "").slice(0, 10);
}

/** Bands alternate above and below the spine: first perspective above, second below, and so on. */
export function bandIndex(perspectives: string[], p: string): number {
  const i = perspectives.indexOf(p);
  return (i % 2 === 0 ? -1 : 1) * (Math.floor(i / 2) + 1);
}

const radius = (n: GraphNode) => (n.kind === "document" ? 9 : Math.min(8 + 3 * Math.sqrt(n.count ?? 1), R_MAX));

export function layout(
  nodes: GraphNode[], edges: GraphEdge[], perspectives: string[], width = 960,
): Layout {
  const days = [...new Set(nodes.map(dayOf).filter(Boolean))].sort();
  const dayW = Math.max(DAY_MIN, (width - GUTTER) / Math.max(days.length, 1));
  const W = GUTTER + dayW * Math.max(days.length, 1);
  const xOf = (d: string) => GUTTER + dayW * (days.indexOf(d) + 0.5);

  const sorted = [...nodes].sort((a, b) => (a.at ?? "").localeCompare(b.at ?? "") || a.id.localeCompare(b.id));
  const bandOf = (n: GraphNode) => (n.kind === "document" ? 0 : bandIndex(perspectives, n.perspective ?? ""));

  // 1. flow the nodes of each (day, lane) cell into rows inside the day column
  type Cell = { band: number; day: string; rows: { items: { n: GraphNode; r: number; dx: number }[]; h: number }[] };
  const cells = new Map<string, Cell>();
  for (const n of sorted) {
    const band = bandOf(n);
    const key = `${dayOf(n)}|${band}`;
    const cell = cells.get(key) ?? { band, day: dayOf(n), rows: [] };
    cells.set(key, cell);
    const r = radius(n);
    const foot = 2 * (r + RING);
    let row = cell.rows[cell.rows.length - 1];
    const used = row ? row.items.reduce((s, i) => s + 2 * (i.r + RING) + GAP, 0) : 0;
    if (!row || used + foot > dayW - GAP) {
      row = { items: [], h: 0 };
      cell.rows.push(row);
    }
    const left = row.items.reduce((s, i) => s + 2 * (i.r + RING) + GAP, 0);
    row.items.push({ n, r, dx: left + r + RING });
    row.h = Math.max(row.h, foot);
  }
  const cellH = (c: Cell) => c.rows.reduce((s, r) => s + r.h + GAP, 0) - (c.rows.length ? GAP : 0);

  // 2. lanes top to bottom: above the spine (outermost first), spine, below the spine
  const bandsUsed = [...new Set([0, ...perspectives.map((p) => bandIndex(perspectives, p))])].sort((a, b) => a - b);
  const laneH = new Map<number, number>();
  for (const b of bandsUsed) {
    const tallest = Math.max(0, ...[...cells.values()].filter((c) => c.band === b).map(cellH));
    laneH.set(b, Math.max(tallest, 2 * (R_MAX + RING)) + 2 * LANE_PAD);
  }
  const lanes: Lane[] = [];
  let y = 0;
  for (const b of bandsUsed) {
    const h = laneH.get(b)!;
    lanes.push({ perspective: b === 0 ? null : (perspectives.find((p) => bandIndex(perspectives, p) === b) ?? null), band: b, top: y, bottom: y + h, mid: y + h / 2 });
    y += h;
  }
  const laneOf = new Map(lanes.map((l) => [l.band, l]));

  // 3. final coordinates
  const placed: Placed[] = [];
  for (const c of cells.values()) {
    const lane = laneOf.get(c.band)!;
    const left = xOf(c.day) - dayW / 2 + GAP / 2;
    let top = lane.mid - cellH(c) / 2;
    for (const row of c.rows) {
      const rowW = row.items.reduce((s, i) => s + 2 * (i.r + RING) + GAP, 0) - GAP;
      const shift = (dayW - GAP - rowW) / 2; // centre each row in the column
      for (const i of row.items) placed.push({ ...i.n, x: left + shift + i.dx, y: top + row.h / 2, r: i.r, band: c.band });
      top += row.h + GAP;
    }
  }
  placed.sort((a, b) => (a.at ?? "").localeCompare(b.at ?? "") || a.id.localeCompare(b.id));

  const out: Layout["edges"] = [];
  for (const e of edges) {
    const [a, b] = e.between.map((ps) => ps[0]);
    const na = placed.find((n) => n.event_id === e.event_id && n.perspective === a);
    const nb = placed.find((n) => n.event_id === e.event_id && n.perspective === b);
    if (na && nb && na !== nb) out.push({ from: na, to: nb, event_id: e.event_id });
  }
  return {
    nodes: placed, edges: out, days: days.map((d) => ({ day: d, x: xOf(d) })), lanes,
    bands: lanes.filter((l) => l.perspective).map((l) => ({ perspective: l.perspective!, y: l.mid })),
    spineY: laneOf.get(0)!.mid, width: W, height: y + AXIS, gutter: GUTTER,
  };
}
