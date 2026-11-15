"use client";
// Owner labels for the anomaly eval set (#114). Shown only to a signed-in admin.
import { useEffect, useState } from "react";
import { adminHeaders } from "@/lib/account";

const LABELS = [["useful", "Useful"], ["not_useful", "Not useful"], ["wrong_grouping", "Wrong grouping"]] as const;

export default function AnomalyFeedback({ id }: { id: string }) {
  const [auth, setAuth] = useState<Record<string, string> | null>(null);
  const [done, setDone] = useState("");
  useEffect(() => { void adminHeaders().then(setAuth); }, []);
  if (!auth) return null;
  if (done) return <span className="muted fs12">Labelled {done.replace("_", " ")}</span>;
  return (
    <span className="row gap6 fs12" aria-label="Label this anomaly">
      {LABELS.map(([v, l]) => (
        <button key={v} className="pill" onClick={async () => {
          const r = await fetch(`/api/admin/anomalies/${id}/feedback`, { method: "POST", headers: { "Content-Type": "application/json", ...auth }, body: JSON.stringify({ label: v }) });
          if (r.ok) setDone(v);
        }}>{l}</button>
      ))}
    </span>
  );
}
