// Marker placement for the globe: markers that would sit on top of each other are moved apart
// along a fixed spiral, so the result depends only on the inputs (no randomness).
export type Pt = { key: string; x: number; y: number; r: number };
export type Placed = Pt & { px: number; py: number; moved: boolean };

const GOLDEN = 2.399963;

/** Place every marker so no two circles overlap. `px, py` is where it is drawn; `x, y` is the true point. */
export function spread(pts: Pt[], gap = 3): Placed[] {
  const placed: Placed[] = [];
  for (const p of [...pts].sort((a, b) => a.key.localeCompare(b.key))) {
    const clash = (x: number, y: number) => placed.some((q) => Math.hypot(q.px - x, q.py - y) < q.r + p.r + gap);
    let px = p.x;
    let py = p.y;
    for (let k = 1; clash(px, py) && k < 400; k++) {
      const d = 3 * Math.sqrt(k) * (p.r / 6 + 1);
      px = p.x + d * Math.cos(k * GOLDEN);
      py = p.y + d * Math.sin(k * GOLDEN);
    }
    placed.push({ ...p, px, py, moved: px !== p.x || py !== p.y });
  }
  return placed;
}

/** Marker radius: grows with reports but is capped relative to the globe size. */
export const radius = (reports: number, globe: number): number => Math.max(4, Math.min(Math.sqrt(reports) * 1.6 + 4, globe * 0.02));

/** Rotation that puts the point (lon, lat) in the middle of the globe. */
export const turnTo = (at: [number, number]): [number, number] => [-at[0], -at[1]];
