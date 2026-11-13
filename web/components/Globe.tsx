"use client";
// Rotatable orthographic globe in SVG. Real country shapes (Natural Earth via world-atlas and
// d3-geo). A story's marker sits on the countries it is about (not where its outlets are);
// size = number of reports; orange ring = story with anomalies; dashed ring = coverage gap
// (a party country we hold few reports from). The story list sits beside it.
import countries from "i18n-iso-countries";
import { geoCentroid, geoDistance, geoGraticule10, geoOrthographic, geoPath } from "d3-geo";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { feature } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";
import land from "world-atlas/countries-110m.json";
import { perspectiveName } from "@/lib/format";
import type { World } from "@/lib/types";

type Marker = {
  key: string; kind: "story" | "gap"; storyId: string; title: string; country: string;
  reports: number; perspectives: number; anomalies: number; provisional: boolean; at: [number, number];
  from?: Record<string, number>;
};
type Filter = "all" | "anomalies" | "gaps";
const W = 560;

export default function Globe({ world, directions = [] }: { world: World; directions?: string[] }) {
  const topo = land as unknown as Topology;
  const features = useMemo(
    () => (feature(topo, topo.objects.countries as GeometryCollection) as unknown as GeoJSON.FeatureCollection).features,
    [topo],
  );
  const centroid = useMemo(() => {
    const m = new Map<string, [number, number]>();
    for (const f of features) {
      const a2 = countries.numericToAlpha2(String(f.id).padStart(3, "0"));
      if (a2) m.set(a2, geoCentroid(f) as [number, number]);
    }
    return m;
  }, [features]);

  const markers: Marker[] = useMemo(() => {
    const out: Marker[] = [];
    for (const s of world.places ?? []) {
      const at = centroid.get(s.country);
      if (at) out.push({ key: `s-${s.story_id}-${s.country}`, kind: "story", storyId: s.story_id, title: s.title, country: s.country, reports: s.reports, perspectives: s.perspectives, anomalies: s.anomalies, provisional: s.provisional, at, from: s.from });
    }
    for (const g of world.gaps) {
      const at = centroid.get(g.country);
      if (at) out.push({ key: `g-${g.story_id}-${g.country}`, kind: "gap", storyId: g.story_id, title: g.title, country: g.country, reports: g.reports, perspectives: 0, anomalies: 0, provisional: false, at });
    }
    return out;
  }, [world, centroid]);

  const [rot, setRot] = useState<[number, number]>([-20, -20]);
  const [filter, setFilter] = useState<Filter>("all");
  const [hover, setHover] = useState<Marker | null>(null);
  const [pinned, setPinned] = useState<Marker | null>(null);
  const drag = useRef<{ x: number; y: number; rot: [number, number] } | null>(null);

  // Slow auto-rotation. Pauses while dragging, hovering, or with a card open, and never runs
  // for people who ask for reduced motion.
  const [paused, setPaused] = useState(false);
  const [dragging, setDragging] = useState(false);
  const idle = !paused && !hover && !pinned && !dragging;
  useEffect(() => {
    if (!idle || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let raf = 0;
    let last = performance.now();
    const tick = (t: number) => {
      const step = Math.min(t - last, 100) * 0.006; // about 6 degrees a second
      last = t;
      setRot(([a, b]) => [a + step, b]);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [idle]);

  const proj = geoOrthographic().scale(W / 2 - 8).translate([W / 2, W / 2]).rotate([rot[0], rot[1]]);
  const path = geoPath(proj);
  const visible = (m: Marker) => geoDistance(m.at, [-rot[0], -rot[1]]) < Math.PI / 2;
  const shown = markers.filter((m) => filter === "all" || (filter === "anomalies" ? m.anomalies > 0 : m.kind === "gap"));
  const card = pinned ?? hover;
  const turn = (to: Marker) => setRot([-to.at[0], -to.at[1]]);

  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(280px, 560px) 1fr", alignItems: "start" }}>
      <div>
        <div className="row" role="group" aria-label="Filter">
          {(["all", "anomalies", "gaps"] as Filter[]).map((f) => (
            <button key={f} className={`pill${filter === f ? " on" : ""}`} aria-pressed={filter === f} onClick={() => setFilter(f)}>
              {f === "all" ? "All" : f === "anomalies" ? "Anomalies" : "Coverage gaps"}
            </button>
          ))}
        </div>
        <svg
          viewBox={`0 0 ${W} ${W}`} role="img" aria-label="Globe of stories by the countries they are about, and coverage gaps" style={{ width: "100%", touchAction: "none", cursor: "grab" }}
          onPointerDown={(e) => { drag.current = { x: e.clientX, y: e.clientY, rot }; setDragging(true); (e.target as Element).setPointerCapture?.(e.pointerId); }}
          onPointerMove={(e) => {
            const d = drag.current;
            if (d) setRot([d.rot[0] + (e.clientX - d.x) * 0.4, Math.max(-80, Math.min(80, d.rot[1] - (e.clientY - d.y) * 0.4))]);
          }}
          onPointerUp={() => { drag.current = null; setDragging(false); }}
        >
          <circle cx={W / 2} cy={W / 2} r={W / 2 - 8} fill="#0b0d10" stroke="var(--hair)" />
          <path d={path(geoGraticule10()) ?? ""} fill="none" stroke="var(--hair)" strokeWidth={0.4} />
          {features.map((f, i) => <path key={i} d={path(f) ?? ""} fill="#161a1f" stroke="#2a2f36" strokeWidth={0.5} />)}
          {shown.filter(visible).map((m) => {
            const p = proj(m.at);
            if (!p) return null;
            const r = 5 + Math.min(Math.sqrt(m.reports) * 2.2, 14);
            return (
              <g
                key={m.key} tabIndex={0} role="button" aria-label={`${m.kind === "gap" ? "Coverage gap" : "Story"}: ${m.title}, ${perspectiveName(m.country)}`}
                onMouseEnter={() => setHover(m)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(m)}
                onClick={() => setPinned(m)} onKeyDown={(e) => e.key === "Enter" && setPinned(m)} style={{ cursor: "pointer" }}
              >
                {m.anomalies > 0 && <circle cx={p[0]} cy={p[1]} r={r + 6} fill="rgba(255,122,69,0.15)" stroke="var(--anomaly)" strokeWidth={2} />}
                {m.kind === "gap"
                  ? <circle cx={p[0]} cy={p[1]} r={r} fill="none" stroke="var(--text)" strokeDasharray="3 3" />
                  : <circle cx={p[0]} cy={p[1]} r={r} fill="var(--text)" opacity={0.9} />}
              </g>
            );
          })}
        </svg>
        <div className="row">
          <button onClick={() => setRot(([a, b]) => [a + 25, b])}>← West</button>
          <button onClick={() => setRot(([a, b]) => [a - 25, b])}>East →</button>
          <button onClick={() => setRot([-20, -20])}>Reset view</button>
          <button aria-pressed={!paused} onClick={() => setPaused((p) => !p)}>{paused ? "Resume rotation" : "Pause rotation"}</button>
        </div>
        {card && (
          <div className="card" role="dialog" aria-label="Marker details">
            <div className={`kicker${card.anomalies ? " anomaly" : ""}`}>
              {card.kind === "gap" ? "Coverage gap" : card.provisional ? "Story · provisional anomalies" : "Story"} · {perspectiveName(card.country)}
            </div>
            <h3>{card.title}</h3>
            <p className="muted">
              {card.kind === "gap"
                ? `We hold ${card.reports} reports from ${perspectiveName(card.country)} on this story. That describes our coverage, not the story.`
                : `About ${perspectiveName(card.country)} · ${card.reports} reports from ${card.perspectives} perspectives`}
            </p>
            {card.from && (
              <p className="muted" style={{ fontSize: 13 }}>
                Reports from: {Object.entries(card.from).map(([c, n]) => `${perspectiveName(c)} ${n}`).join(" · ")}
              </p>
            )}
            <Link href={`/s/${card.storyId}`}>Open the story</Link>
            {directions.includes(card.country) && (
              <Link href={`/directions?subject=${card.country}`} style={{ marginLeft: 12 }}>Directions for {perspectiveName(card.country)}</Link>
            )}
            {pinned && <button style={{ marginLeft: 12 }} onClick={() => setPinned(null)}>Close</button>}
          </div>
        )}
      </div>
      <div>
        <div className="kicker">Coverage gaps</div>
        {world.gaps.length ? world.gaps.map((g) => (
          <div className="card" key={`${g.story_id}-${g.country}`}>
            <b>{perspectiveName(g.country)}</b> · {g.reports} reports on <Link href={`/s/${g.story_id}`}>{g.title}</Link>
          </div>
        )) : <p className="muted">No gaps recorded.</p>}
        <div className="kicker" style={{ marginTop: 18 }}>Stories on the globe, by where they happen</div>
        {markers.filter((m) => m.kind === "story").map((m) => (
          <button key={m.key} style={{ display: "block", width: "100%", textAlign: "left", margin: "6px 0" }} onClick={() => { turn(m); setPinned(m); }}>
            {perspectiveName(m.country)} · {m.title} · {m.reports}
          </button>
        ))}
      </div>
    </div>
  );
}
