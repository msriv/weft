"use client";
// SVG story graph up to ~300 nodes (d3-scale for sizing, d3-shape for edges); beyond that the same
// layout is drawn on a PixiJS canvas. The list view is the default for screen readers.
import { scaleLinear } from "d3-scale";
import { line, curveBasis } from "d3-shape";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { day, perspectiveName } from "@/lib/format";
import { layout, type Placed } from "@/lib/layout";
import type { Anomaly, GraphEdge, GraphNode } from "@/lib/types";
import StoryCanvas from "./StoryCanvas";

const CANVAS_ABOVE = 300;

export default function StoryGraph(props: {
  storyId: string; nodes: GraphNode[]; edges: GraphEdge[]; perspectives: string[]; anomalies: Anomaly[];
}) {
  const { nodes, edges, perspectives, anomalies, storyId } = props;
  const L = useMemo(() => layout(nodes, edges, perspectives), [nodes, edges, perspectives]);
  const [sel, setSel] = useState<Placed | null>(null);
  const router = useRouter();
  const params = useSearchParams();
  const days = L.days.map((d) => d.day);
  const at = params.get("at") ?? days[days.length - 1] ?? "";
  const dayScale = scaleLinear().domain([0, Math.max(days.length - 1, 1)]).range([0, 1]);
  const curve = line<[number, number]>().curve(curveBasis);
  const anomalyById = new Map(anomalies.map((a) => [a.id, a]));

  if (nodes.length === 0) {
    return <p className="muted">No reports in the graph for this date.</p>;
  }
  return (
    <div>
      <div className="graph" role="group" aria-label="Story graph. A list view with the same data is available.">
        {nodes.length > CANVAS_ABOVE ? (
          <StoryCanvas layout={L} onSelect={setSel} />
        ) : (
          <svg viewBox={`0 0 ${L.width} ${L.height}`} role="img" aria-label={`${nodes.length} nodes by day`}>
            {L.days.map((d) => (
              <g key={d.day}>
                <line x1={d.x} x2={d.x} y1={0} y2={L.height} stroke="var(--hair)" />
                <text x={d.x} y={L.height - 4} textAnchor="middle" fill="var(--muted)" fontSize={10}>{d.day.slice(5)}</text>
              </g>
            ))}
            <line x1={0} x2={L.width} y1={L.spineY} y2={L.spineY} stroke="var(--hair)" strokeDasharray="2 6" />
            {L.bands.map((b) => (
              <text key={b.perspective} x={8} y={b.y - 40} fill="var(--muted)" fontSize={10}>
                {perspectiveName(b.perspective).toUpperCase()}
              </text>
            ))}
            {L.edges.map((e) => (
              <path
                key={`${e.from.id}-${e.to.id}`} fill="none" stroke="var(--anomaly)" strokeDasharray="4 4" opacity={0.8}
                d={curve([[e.from.x, e.from.y], [(e.from.x + e.to.x) / 2, L.spineY], [e.to.x, e.to.y]]) ?? ""}
              />
            ))}
            {L.nodes.map((n) => {
              const doc = n.kind === "document";
              const party = doc && n.issuer?.is_party;
              const flagged = n.anomalies.some((id) => anomalyById.get(id)?.status === "active");
              const prov = n.anomalies.some((id) => anomalyById.get(id)?.status === "provisional");
              const label = doc ? `${n.title ?? "Document"}, issued by ${n.issuer?.name ?? "unknown"}` : `${n.count} reports from ${perspectiveName(n.perspective ?? "")}, ${day(n.at)}`;
              return (
                <g
                  key={n.id} className="node fade-in" tabIndex={0} role="button" aria-label={label}
                  onClick={() => setSel(n)} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setSel(n)}
                  style={{ cursor: "pointer" }}
                >
                  {(flagged || prov) && (
                    <circle cx={n.x} cy={n.y} r={n.r + 6} fill="none" stroke="var(--anomaly)" strokeWidth={2}
                      strokeDasharray={prov ? "3 3" : undefined} />
                  )}
                  {doc ? (
                    <circle cx={n.x} cy={n.y} r={n.r} fill={party ? "var(--party)" : "var(--text)"} />
                  ) : (
                    <circle cx={n.x} cy={n.y} r={n.r} fill="none" stroke="var(--text)" strokeDasharray="3 3" />
                  )}
                  {!doc && <text x={n.x} y={n.y + 4} textAnchor="middle" fontSize={11} fill="var(--text)">{n.count}</text>}
                </g>
              );
            })}
          </svg>
        )}
      </div>
      {days.length > 1 && (
        <div className="row" style={{ margin: "12px 0" }}>
          <label className="kicker" htmlFor="replay">Replay</label>
          <input
            id="replay" type="range" min={0} max={days.length - 1} step={1}
            value={Math.max(days.indexOf(at), 0)}
            onChange={(e) => router.push(`/s/${storyId}?at=${days[Number(e.target.value)]}`)}
            aria-valuetext={at}
          />
          <span className="muted">{at} ({Math.round(dayScale(Math.max(days.indexOf(at), 0)) * 100)}%)</span>
          <Link href={`/s/${storyId}`} className="muted">Now</Link>
        </div>
      )}
      <Legend />
      {sel && <Detail n={sel} anomalies={anomalies} onClose={() => setSel(null)} />}
    </div>
  );
}

function Legend() {
  return (
    <div className="row muted" style={{ fontSize: 12 }}>
      <span>● Grey: document from a party to the story</span><span>● Bright: independent document</span>
      <span>◌ Dashed: group of reports, number = how many</span>
      <span style={{ color: "var(--anomaly)" }}>◯ Orange ring: anomaly (dashed: provisional)</span>
      <span style={{ color: "var(--anomaly)" }}>┄ Dashed orange line: conflicting reports</span>
    </div>
  );
}

function Detail({ n, anomalies, onClose }: { n: Placed; anomalies: Anomaly[]; onClose: () => void }) {
  const mine = anomalies.filter((a) => n.anomalies.includes(a.id));
  return (
    <div className="card" role="region" aria-label="Selected node">
      <div className="row"><button onClick={onClose}>Close</button></div>
      {n.kind === "document" ? (
        <>
          <div className="kicker">{n.doc_kind} · {day(n.at)}</div>
          <h3>{n.title}</h3>
          <p>{n.issuer ? `Issued by ${n.issuer.name}, ${n.issuer.is_party ? "a party to this story: this is that party's account." : "not a party to this story."}` : ""}</p>
          <Link href={`/d/${n.id}`}>Open the document page</Link>
        </>
      ) : (
        <>
          <div className="kicker">Reports · {perspectiveName(n.perspective ?? "")} · {day(n.at)}</div>
          <h3>{n.count} reports</h3>
          <p>{n.sources?.join(", ")}</p>
          <a href={`#event-${n.event_id}`}>Jump to this event in the list</a>
        </>
      )}
      {mine.map((a) => <p key={a.id} style={{ color: "var(--anomaly-light)" }}>{a.summary}</p>)}
    </div>
  );
}
