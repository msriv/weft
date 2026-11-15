"use client";
// SVG story graph up to ~300 nodes; beyond that the same layout is drawn on a PixiJS canvas. The
// list view is the default for screen readers. Hover or focus on a node lights up every node of
// the same event; selecting one opens a panel beside the graph.
import { line, curveBasis } from "d3-shape";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useRef, useState } from "react";
import { count, dateShort, perspectiveName, RULE_NAMES, shortDay } from "@/lib/format";
import { layout, type Placed } from "@/lib/layout";
import type { Anomaly, GraphEdge, GraphNode } from "@/lib/types";
import StoryCanvas from "./StoryCanvas";

const CANVAS_ABOVE = 300;

const names = (label: string): string[] => {
  if (label.length <= 17) return [label];
  const w = label.split(" ");
  const half = Math.ceil(w.length / 2);
  return [w.slice(0, half).join(" "), w.slice(half).join(" ")].filter(Boolean);
};

type Props = {
  storyId: string; nodes: GraphNode[]; edges: GraphEdge[]; perspectives: string[]; anomalies: Anomaly[];
  events?: { id: string; label: string | null }[];
};

export default function StoryGraph(props: Props) {
  const { nodes, edges, perspectives, anomalies, storyId } = props;
  const L = useMemo(() => layout(nodes, edges, perspectives), [nodes, edges, perspectives]);
  const [sel, setSel] = useState<Placed | null>(null);
  const [hot, setHot] = useState<{ n: Placed } | null>(null);
  const router = useRouter();
  const params = useSearchParams();
  const svg = useRef<SVGSVGElement>(null);
  const days = L.days.map((d) => d.day);
  const at = params.get("at") ?? days[days.length - 1] ?? "";
  const [pick, setPick] = useState<number | null>(null);
  const idx = pick ?? Math.max(days.indexOf(at), 0);
  const curve = line<[number, number]>().curve(curveBasis);
  const anomalyById = new Map(anomalies.map((a) => [a.id, a]));
  const eventLabel = (id: string | null) => props.events?.find((e) => e.id === id)?.label ?? "Event";
  const today = new Date().toISOString().slice(0, 10);

  // event connectors: one thin line through the nodes of an event, top to bottom
  const byEvent = useMemo(() => {
    const m = new Map<string, Placed[]>();
    for (const n of L.nodes) if (n.event_id && n.kind === "report_group") m.set(n.event_id, [...(m.get(n.event_id) ?? []), n]);
    return [...m.entries()].filter(([, v]) => v.length > 1).map(([id, v]) => [id, [...v].sort((a, b) => a.y - b.y || a.x - b.x)] as const);
  }, [L]);

  const move = (from: number, step: number) => {
    const next = L.nodes[Math.min(Math.max(from + step, 0), L.nodes.length - 1)];
    (svg.current?.querySelector(`[data-node="${next.id}"]`) as SVGGElement | null)?.focus();
  };
  const commit = () => {
    if (pick == null) return;
    const q = new URLSearchParams(params.toString());
    if (pick >= days.length - 1) q.delete("at"); else q.set("at", days[pick]);
    router.replace(`/s/${storyId}${q.size ? `?${q}` : ""}`, { scroll: false });
    setPick(null);
  };

  if (nodes.length === 0) return <p className="muted">No reports in the graph for this date.</p>;
  const shown = hot?.n.event_id ?? null;
  return (
    <div onKeyDown={(e) => e.key === "Escape" && setSel(null)}>
      <div className={`graph-grid${sel ? " has-panel" : ""}`}>
        <div className="graph" role="group" aria-label="Story graph. A list view with the same data is available." style={{ position: "relative" }}>
          {nodes.length > CANVAS_ABOVE ? (
            <StoryCanvas layout={L} onSelect={setSel} />
          ) : (
            <svg ref={svg} viewBox={`0 0 ${L.width} ${L.height}`} role="img" aria-label={`${nodes.length} nodes by day`}>
              {L.lanes.map((l) => (
                <g key={l.band}>
                  <line x1={0} x2={L.width} y1={l.top} y2={l.top} stroke="var(--hair)" />
                  {l.perspective ? names(perspectiveName(l.perspective)).map((t, i, a) => (
                    <text key={i} x={8} y={l.mid + (i - (a.length - 1) / 2) * 15 + 4} fill="var(--body2)" fontSize={12}>{t}</text>
                  )) : <text x={8} y={l.mid + 4} fill="var(--muted)" fontSize={12}>Official documents</text>}
                </g>
              ))}
              {L.days.map((d) => (
                <g key={d.day}>
                  <line x1={d.x} x2={d.x} y1={0} y2={L.height - 28} stroke={d.day === today ? "var(--text)" : "var(--hair)"} strokeDasharray={d.day === today ? undefined : "2 6"} />
                  <text x={d.x} y={L.height - 8} textAnchor="middle" fill="var(--muted)" fontSize={12}>{d.day === today ? "today" : shortDay(d.day)}</text>
                </g>
              ))}
              {byEvent.map(([id, ns]) => (
                <path key={id} d={`M${ns.map((n) => `${n.x},${n.y}`).join("L")}`} fill="none" stroke="var(--text)"
                  strokeWidth={shown === id ? 1.5 : 0.75} opacity={shown === id ? 0.7 : 0.12} />
              ))}
              {L.edges.map((e) => (
                <path
                  key={`${e.from.id}-${e.to.id}`} fill="none" stroke="var(--anomaly)" strokeDasharray="4 4" opacity={0.8}
                  d={curve([[e.from.x, e.from.y], [(e.from.x + e.to.x) / 2, (e.from.y + e.to.y) / 2], [e.to.x, e.to.y]]) ?? ""}
                />
              ))}
              {L.nodes.map((n, i) => {
                const doc = n.kind === "document";
                const party = doc && n.issuer?.is_party;
                const flagged = n.anomalies.some((id) => anomalyById.get(id)?.status === "active");
                const prov = n.anomalies.some((id) => anomalyById.get(id)?.status === "provisional");
                const label = doc ? `${n.title ?? "Document"}, issued by ${n.issuer?.name ?? "unknown"}` : `${eventLabel(n.event_id)}: ${count(n.count ?? 0, "report")} from ${perspectiveName(n.perspective ?? "")}, ${dateShort(n.at ?? "")}`;
                const dim = shown != null && n.event_id !== shown;
                return (
                  <g
                    key={n.id} data-node={n.id} className="node pointer" tabIndex={0} role="button" aria-label={label} aria-pressed={sel?.id === n.id}
                    opacity={dim ? 0.25 : 1}
                    onClick={() => setSel(n)} onMouseEnter={() => setHot({ n })} onMouseLeave={() => setHot(null)}
                    onFocus={() => setHot({ n })} onBlur={() => setHot(null)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSel(n); }
                      else if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); move(i, 1); }
                      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); move(i, -1); }
                    }}
                  >
                    {/* a larger invisible target keeps small nodes tappable */}
                    <circle cx={n.x} cy={n.y} r={Math.max(n.r + 6, 22)} fill="transparent" />
                    {(flagged || prov) && (
                      <circle cx={n.x} cy={n.y} r={n.r + 5} fill="none" stroke="var(--anomaly)" strokeWidth={2} strokeDasharray={prov ? "3 3" : undefined} />
                    )}
                    {doc ? (
                      <circle cx={n.x} cy={n.y} r={n.r} fill={party ? "var(--party)" : "var(--text)"} />
                    ) : (
                      <circle cx={n.x} cy={n.y} r={n.r} fill="var(--bg)" stroke="var(--text)" strokeDasharray="3 3" />
                    )}
                    {!doc && <text x={n.x} y={n.y + 4} textAnchor="middle" fontSize={12} fill="var(--text)">{n.count}</text>}
                  </g>
                );
              })}
            </svg>
          )}
          {hot && (
            <div className="tip card" role="status" style={{ left: `${(hot.n.x / L.width) * 100}%`, top: `${(hot.n.y / L.height) * 100}%` }}>
              <strong>{hot.n.kind === "document" ? hot.n.title : eventLabel(hot.n.event_id)}</strong>
              <div className="muted fs12">
                {hot.n.kind === "document" ? `Issued by ${hot.n.issuer?.name ?? "unknown"}` : `${perspectiveName(hot.n.perspective ?? "")} · ${count(hot.n.count ?? 0, "report")} · ${(hot.n.sources ?? []).join(", ")}`}
              </div>
              {hot.n.anomalies.map((id) => anomalyById.get(id)).filter(Boolean).map((a) => (
                <div key={a!.id} className="c-anomaly-light fs12">Anomaly: {RULE_NAMES[a!.rule] ?? a!.rule}</div>
              ))}
            </div>
          )}
        </div>
        {sel && <Detail n={sel} storyId={storyId} eventLabel={eventLabel(sel.event_id)} anomalies={anomalies} onClose={() => setSel(null)} />}
      </div>
      {days.length > 1 && (
        <div className="row my12">
          <label className="kicker" htmlFor="replay">Replay</label>
          <input
            id="replay" type="range" min={0} max={days.length - 1} step={1} className="replay" list="replay-days"
            value={idx} aria-valuetext={shortDay(days[idx])}
            onChange={(e) => setPick(Number(e.target.value))}
            onPointerUp={commit} onKeyUp={commit} onBlur={commit}
          />
          <datalist id="replay-days">{days.map((d, i) => <option key={d} value={i} label={shortDay(d)} />)}</datalist>
          <span className="muted">{params.get("at") || pick != null ? `Showing the story as of ${shortDay(days[idx])}` : "Showing the story as it stands now"}</span>
          {params.get("at") && <Link href={`/s/${storyId}`} className="muted">Back to now</Link>}
        </div>
      )}
      <Legend />
    </div>
  );
}

const Mark = ({ children }: { children: React.ReactNode }) => (
  <svg width={18} height={18} viewBox="0 0 18 18" aria-hidden="true" className="mark">{children}</svg>
);
function Legend() {
  return (
    <div className="legend muted fs12">
      <span><Mark><circle cx={9} cy={9} r={6} fill="var(--party)" /></Mark>Document from a party to the story</span>
      <span><Mark><circle cx={9} cy={9} r={6} fill="var(--text)" /></Mark>Document from an issuer not listed as a party</span>
      <span><Mark><circle cx={9} cy={9} r={6} fill="none" stroke="var(--text)" strokeDasharray="3 3" /></Mark>Group of reports (number = how many)</span>
      <span className="c-anomaly"><Mark><circle cx={9} cy={9} r={7} fill="none" stroke="var(--anomaly)" strokeWidth={2} /></Mark>Anomaly (dashed: provisional)</span>
      <span className="c-anomaly"><Mark><line x1={1} x2={17} y1={9} y2={9} stroke="var(--anomaly)" strokeDasharray="4 3" /></Mark>Conflicting reports</span>
    </div>
  );
}

function Detail({ n, storyId, eventLabel, anomalies, onClose }: { n: Placed; storyId: string; eventLabel: string; anomalies: Anomaly[]; onClose: () => void }) {
  const mine = anomalies.filter((a) => n.anomalies.includes(a.id));
  return (
    <aside className="card graph-panel" role="region" aria-label="Selected node">
      <div className="row"><button className="small" onClick={onClose}>Close</button></div>
      {n.kind === "document" ? (
        <>
          <div className="kicker">{n.doc_kind} · {shortDay(n.at ?? "")}</div>
          <h3>{n.title}</h3>
          <p>{n.issuer ? `Issued by ${n.issuer.name}, ${n.issuer.is_party ? "a party to this story: this is that party's account." : "not a party to this story."}` : ""}</p>
          <Link href={`/d/${n.id}`}>Open the document page</Link>
        </>
      ) : (
        <>
          <div className="kicker">{perspectiveName(n.perspective ?? "")} · {shortDay(n.at ?? "")}</div>
          <h3>{eventLabel}</h3>
          <p>{count(n.count ?? 0, "report")} from {(n.sources ?? []).join(", ") || "outlets not named"}</p>
          {n.event_id && <Link href={`/s/${storyId}/e/${n.event_id}`}>Open this event</Link>}
        </>
      )}
      {mine.map((a) => <p key={a.id} className="c-anomaly-light">{a.summary}</p>)}
    </aside>
  );
}
