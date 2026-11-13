"use client";
// Owner labels for the anomaly eval set (#114). Shown only when the admin token is in this tab.
import { useEffect, useState } from "react";

const LABELS = [["useful", "Useful"], ["not_useful", "Not useful"], ["wrong_grouping", "Wrong grouping"]] as const;

export default function AnomalyFeedback({ id }: { id: string }) {
  const [token, setToken] = useState("");
  const [done, setDone] = useState("");
  useEffect(() => { setToken(sessionStorage.getItem("weft:admin") ?? ""); }, []);
  if (!token) return null;
  if (done) return <span className="muted" style={{ fontSize: 12 }}>Labelled {done.replace("_", " ")}</span>;
  return (
    <span className="row" style={{ gap: 6, fontSize: 12 }} aria-label="Label this anomaly">
      {LABELS.map(([v, l]) => (
        <button key={v} className="pill" onClick={async () => {
          const r = await fetch(`/api/admin/anomalies/${id}/feedback`, { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify({ label: v }) });
          if (r.ok) setDone(v);
        }}>{l}</button>
      ))}
    </span>
  );
}
