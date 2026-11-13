"use client";
// Live mode (opt-in, decision D10): new nodes arrive over server-sent events. Motion is off under
// prefers-reduced-motion (see .fade-in in globals.css). Provisional anomalies are marked as such.
import { useEffect, useState } from "react";

type Msg = { type: string; at: string; data: Record<string, unknown> };
const LABEL: Record<string, string> = {
  "node.added": "New report", "edge.added": "New link", "anomaly.updated": "Anomaly updated", "event.merged": "Events merged",
};

export default function LiveFeed({ storyId }: { storyId: string }) {
  const [items, setItems] = useState<Msg[]>([]);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const es = new EventSource(`/api/v1/stories/${storyId}/stream`);
    es.onopen = () => setOpen(true);
    es.onerror = () => setOpen(false);
    for (const type of Object.keys(LABEL)) {
      es.addEventListener(type, (ev) => {
        const data = JSON.parse((ev as MessageEvent).data) as Record<string, unknown>;
        setItems((xs) => [{ type, at: new Date().toISOString(), data }, ...xs].slice(0, 50));
      });
    }
    return () => es.close();
  }, [storyId]);
  return (
    <section className="card" aria-live="polite" aria-label="Live updates">
      <div className="kicker">Live · {open ? "connected" : "reconnecting"}</div>
      {items.length === 0 && <p className="muted">Waiting for new reports. Nothing has arrived since you opened this page.</p>}
      {items.map((m, i) => (
        <div key={i} className="fade-in">
          {LABEL[m.type]} {m.data.status === "provisional" ? <span className="pill">provisional</span> : null}
          {m.type === "node.added" && typeof m.data.title === "string" && (
            <>: <a href={`/nodes/${m.data.id}`}>{m.data.title}</a>{typeof m.data.source === "string" && <span className="muted"> · {m.data.source}</span>}
              {typeof m.data.url === "string" && <> · <a href={m.data.url} rel="noopener noreferrer">Original ↗</a></>}</>
          )}
          {m.type === "anomaly.updated" && typeof m.data.summary === "string" && <>: <a href={`/nodes/${m.data.id}`}>{m.data.summary}</a></>}
          <span className="muted"> {m.at.slice(11, 19)}</span>
        </div>
      ))}
    </section>
  );
}
