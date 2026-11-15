"use client";
// Rotatable orthographic globe. Land is drawn on a canvas so idle rotation does not go through
// React for every country; markers are a small SVG overlay so each one is a real, focusable
// button. A story's marker sits on the countries it is about (not where its outlets are);
// size = number of reports; orange ring = story with anomalies; hatched ring = coverage gap
// (a party country we hold few reports from). Client only: see GlobeLoader.
import countries from "i18n-iso-countries";
import { geoCentroid, geoDistance, geoGraticule10, geoOrthographic, geoPath } from "d3-geo";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { feature } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";
import land from "world-atlas/countries-110m.json";
import { count, perspectiveName } from "@/lib/format";
import { radius, spread, turnTo } from "@/lib/globe";
import type { World } from "@/lib/types";

type Marker = {
  key: string; kind: "story" | "gap"; storyId: string; title: string; country: string;
  reports: number; perspectives: number; anomalies: number; provisional: boolean; at: [number, number];
  from?: Record<string, number>;
};
type Filter = "all" | "anomalies" | "gaps";
const W = 560;
const ZOOM: [number, number] = [0.8, 2.6];

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

  // one row per story, with every country it is about
  const rows = useMemo(() => {
    const m = new Map<string, { storyId: string; title: string; reports: number; anomalies: number; countries: string[]; first: Marker }>();
    for (const k of markers.filter((x) => x.kind === "story")) {
      const r = m.get(k.storyId);
      if (r) { r.countries.push(k.country); r.reports = Math.max(r.reports, k.reports); r.anomalies = Math.max(r.anomalies, k.anomalies); }
      else m.set(k.storyId, { storyId: k.storyId, title: k.title, reports: k.reports, anomalies: k.anomalies, countries: [k.country], first: k });
    }
    return [...m.values()];
  }, [markers]);

  const [rot, setRot] = useState<[number, number]>([-20, -20]);
  const [zoom, setZoom] = useState(1);
  const [filter, setFilter] = useState<Filter>("all");
  const [hover, setHover] = useState<Marker | null>(null);
  const [pinned, setPinned] = useState<Marker | null>(null);
  const [hl, setHl] = useState<string | null>(null); // story highlighted from the list
  const drag = useRef<{ x: number; y: number; rot: [number, number] } | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const wrap = useRef<HTMLDivElement>(null);

  // Slow auto-rotation, about 6 degrees a second, drawn at most 20 times a second. Pauses while
  // dragging, hovering, with a card open, when the tab is hidden or the globe is off screen, and
  // never runs for people who ask for reduced motion.
  const [paused, setPaused] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [away, setAway] = useState(false);
  const idle = !paused && !hover && !pinned && !dragging && !away;
  useEffect(() => {
    const hide = () => setAway(document.hidden);
    document.addEventListener("visibilitychange", hide);
    const io = new IntersectionObserver(([e]) => setAway(document.hidden || !e.isIntersecting));
    if (wrap.current) io.observe(wrap.current);
    return () => { document.removeEventListener("visibilitychange", hide); io.disconnect(); };
  }, []);
  useEffect(() => {
    if (!idle || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let raf = 0;
    let last = performance.now();
    const tick = (t: number) => {
      raf = requestAnimationFrame(tick);
      if (t - last < 50) return;
      const step = Math.min(t - last, 200) * 0.006;
      last = t;
      setRot(([a, b]) => [a + step, b]);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [idle]);

  const R = (W / 2 - 8) * zoom;
  const proj = useMemo(() => geoOrthographic().scale(R).translate([W / 2, W / 2]).rotate([rot[0], rot[1]]), [R, rot]);

  // land and graticule: one canvas draw per frame, no React nodes
  useEffect(() => {
    const c = canvas.current;
    const ctx = c?.getContext("2d");
    if (!c || !ctx) return;
    const dpr = window.devicePixelRatio || 1;
    if (c.width !== W * dpr) { c.width = W * dpr; c.height = W * dpr; }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, W);
    const path = geoPath(proj, ctx);
    ctx.beginPath(); path({ type: "Sphere" }); ctx.fillStyle = "#0b0d10"; ctx.fill(); ctx.strokeStyle = "#2a2f36"; ctx.lineWidth = 1; ctx.stroke();
    ctx.beginPath(); path(geoGraticule10()); ctx.strokeStyle = "rgba(255,255,255,0.08)"; ctx.lineWidth = 0.4; ctx.stroke();
    ctx.beginPath(); for (const f of features) path(f); ctx.fillStyle = "#161a1f"; ctx.fill(); ctx.strokeStyle = "#2a2f36"; ctx.lineWidth = 0.5; ctx.stroke();
  }, [proj, features]);

  const counts = { all: markers.length, anomalies: markers.filter((m) => m.anomalies > 0).length, gaps: markers.filter((m) => m.kind === "gap").length };
  const shown = markers.filter((m) => filter === "all" || (filter === "anomalies" ? m.anomalies > 0 : m.kind === "gap"));
  const placed = useMemo(() => {
    const centre: [number, number] = [-rot[0], -rot[1]];
    const pts = shown.filter((m) => geoDistance(m.at, centre) < Math.PI / 2).flatMap((m) => {
      const p = proj(m.at);
      return p ? [{ key: m.key, x: p[0], y: p[1], r: radius(m.reports, W) }] : [];
    });
    return new Map(spread(pts).map((p) => [p.key, p]));
  }, [shown, proj, rot]);
  const card = pinned;
  const turn = useCallback((to: Marker) => setRot(turnTo(to.at)), []);
  const act = (m: Marker) => setPinned(m);

  return (
    <div className="grid globe-layout">
      <div>
        <div className="row" role="group" aria-label="Filter">
          {(["all", "anomalies", "gaps"] as Filter[]).map((f) => (
            <button key={f} className={`pill${filter === f ? " on" : ""}`} aria-pressed={filter === f} onClick={() => setFilter(f)}>
              {f === "all" ? "All" : f === "anomalies" ? "With anomalies" : "Coverage gaps"} {counts[f]}
            </button>
          ))}
        </div>
        <div className="globe-wrap" ref={wrap}>
          <canvas ref={canvas} className="globe-canvas" width={W} height={W} aria-hidden="true" />
          <svg
            viewBox={`0 0 ${W} ${W}`} role="group" aria-label="Globe of stories by the countries they are about, and coverage gaps" className="globe-svg"
            onWheel={(e) => { if (e.ctrlKey || e.metaKey) setZoom((z) => Math.max(ZOOM[0], Math.min(ZOOM[1], z - e.deltaY * 0.005))); }}
            onPointerDown={(e) => { drag.current = { x: e.clientX, y: e.clientY, rot }; setDragging(true); }}
            onPointerMove={(e) => {
              const d = drag.current;
              if (d) setRot([d.rot[0] + (e.clientX - d.x) * 0.4 / zoom, Math.max(-80, Math.min(80, d.rot[1] - (e.clientY - d.y) * 0.4 / zoom))]);
            }}
            onPointerUp={() => { drag.current = null; setDragging(false); }}
          >
            <defs>
              <pattern id="hatch" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <line x1="0" y1="0" x2="0" y2="4" stroke="var(--text)" strokeWidth="1.5" />
              </pattern>
            </defs>
            {shown.map((m) => {
              const p = placed.get(m.key);
              if (!p) return null;
              const on = hl === m.storyId;
              return (
                <g
                  key={m.key} tabIndex={0} role="button" aria-label={`${m.kind === "gap" ? "Coverage gap" : "Story"}: ${m.title}, ${perspectiveName(m.country)}`}
                  onMouseEnter={() => setHover(m)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(m)} onBlur={() => setHover(null)}
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={() => act(m)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); act(m); } }} className="pointer"
                >
                  {p.moved && <line x1={p.x} y1={p.y} x2={p.px} y2={p.py} stroke="var(--muted)" strokeWidth={1} />}
                  {p.moved && <circle cx={p.x} cy={p.y} r={1.5} fill="var(--muted)" />}
                  {on && <circle cx={p.px} cy={p.py} r={p.r + 9} fill="none" stroke="var(--text)" strokeWidth={1.5} />}
                  {m.anomalies > 0 && <circle cx={p.px} cy={p.py} r={p.r + 4} fill="rgba(255,122,69,0.15)" stroke="var(--anomaly)" strokeWidth={2} />}
                  {m.kind === "gap"
                    ? <circle cx={p.px} cy={p.py} r={p.r} fill="url(#hatch)" stroke="var(--text)" strokeWidth={1.5} />
                    : <circle cx={p.px} cy={p.py} r={p.r} fill="var(--text)" opacity={0.9} />}
                </g>
              );
            })}
          </svg>
          {hover && !dragging && placed.get(hover.key) && (
            <div className="globe-tip" role="tooltip" style={{ left: `${(placed.get(hover.key)!.px / W) * 100}%`, top: `${(placed.get(hover.key)!.py / W) * 100}%` }}>
              <b>{hover.title}</b><br />{perspectiveName(hover.country)} · {count(hover.reports, "report")}
            </div>
          )}
          <div className="globe-zoom" role="group" aria-label="Zoom">
            <button aria-label="Zoom in" disabled={zoom >= ZOOM[1]} onClick={() => setZoom((z) => Math.min(ZOOM[1], z + 0.3))}>+</button>
            <button aria-label="Zoom out" disabled={zoom <= ZOOM[0]} onClick={() => setZoom((z) => Math.max(ZOOM[0], z - 0.3))}>−</button>
          </div>
        </div>
        <div className="row">
          <button onClick={() => setRot(([a, b]) => [a + 25, b])}>← West</button>
          <button onClick={() => setRot(([a, b]) => [a - 25, b])}>East →</button>
          <button onClick={() => { setRot([-20, -20]); setZoom(1); }}>Reset view</button>
          <button aria-pressed={!paused} onClick={() => setPaused((p) => !p)}>{paused ? "Resume rotation" : "Pause rotation"}</button>
        </div>
      </div>
      <div>
        {card && (
          <div className="card" role="dialog" aria-label="Marker details">
            <div className={`kicker${card.anomalies ? " anomaly" : ""}`}>
              {card.kind === "gap" ? "Coverage gap" : card.provisional ? "Story · provisional anomalies" : "Story"} · {perspectiveName(card.country)}
            </div>
            <h3>{card.title}</h3>
            <p className="muted">
              {card.kind === "gap"
                ? `We hold ${count(card.reports, "report")} from ${perspectiveName(card.country)} on this story. That describes our coverage, not the story.`
                : `About ${perspectiveName(card.country)} · ${count(card.reports, "report")} from ${count(card.perspectives, "perspective")}`}
            </p>
            {card.from && (
              <div className="fs13" aria-label="Where the reports come from">
                <div className="muted">Reports come from</div>
                {Object.entries(card.from).sort((a, b) => b[1] - a[1]).map(([c, n]) => (
                  <div className="bar-row" key={c}><span>{perspectiveName(c)}</span><span className="bar"><i style={{ width: `${(n / Math.max(...Object.values(card.from!))) * 100}%` }} /></span><span>{n}</span></div>
                ))}
              </div>
            )}
            <div className="row">
              <Link href={`/s/${card.storyId}`}>Open the story</Link>
              {directions.includes(card.country) && <Link href={`/directions?subject=${card.country}`}>Directions for {perspectiveName(card.country)}</Link>}
              <button onClick={() => setPinned(null)}>Close</button>
            </div>
          </div>
        )}
        <div className="kicker">Coverage gaps</div>
        {world.gaps.length ? world.gaps.map((g) => (
          <div className="card" key={`${g.story_id}-${g.country}`}>
            <b>{perspectiveName(g.country)}</b> · {count(g.reports, "report")} on <Link href={`/s/${g.story_id}`}>{g.title}</Link>
          </div>
        )) : <p className="muted">No gaps recorded.</p>}
        <div className="kicker mt18">Stories on the globe</div>
        {rows.map((r) => (
          <button
            key={r.storyId} className="block w100 tal my6 story-row" onMouseEnter={() => setHl(r.storyId)} onMouseLeave={() => setHl(null)}
            onFocus={() => setHl(r.storyId)} onBlur={() => setHl(null)} onClick={() => { turn(r.first); setPinned(r.first); }}
          >
            <span className="story-title">{r.title}</span>
            <span className="row fs12">
              {r.countries.map((c) => <span className="pill" key={c}>{perspectiveName(c)}</span>)}
              <span className="muted">{count(r.reports, "report")}</span>
              {r.anomalies > 0 && <span className="pill anomaly">Anomaly</span>}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
