"use client";
import { useCallback, useEffect, useState } from "react";
import { Kicker } from "@/components/bits";

type Story = { id: string; beat_id: string; title: string; public: boolean };
type Item = { id: string; kind: string; payload: Record<string, unknown> };
type Problem = { id: number; kind: string; ref_id: string | null; message: string };
type Src = { id: string; name: string; domain: string; country: string | null; country_source: string | null; paywalled: number; status: string; last_report_at: string | null };
type Run = { run_id: string; stage: string; started_at: string; ended_at: string | null; rows_out: number | null; status: string; error: string | null };

export default function Admin() {
  const [token, setToken] = useState("");
  const [stories, setStories] = useState<Story[]>([]);
  const [review, setReview] = useState<{ open: Item[] } | null>(null);
  const [problems, setProblems] = useState<Problem[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [sources, setSources] = useState<Src[]>([]);
  const [err, setErr] = useState("");
  const call = useCallback(async (path: string, init: RequestInit = {}) => {
    const r = await fetch(`/api/admin${path}`, { ...init, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` } });
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  }, [token]);
  const load = useCallback(async () => {
    try {
      setErr("");
      setStories(await call("/stories")); setReview(await call("/review")); setProblems(await call("/reader-reports")); setRuns(await call("/runs")); setSources(await call("/sources"));
    } catch { setErr("Could not load. Check the token."); }
  }, [call]);
  useEffect(() => { setToken(sessionStorage.getItem("weft:admin") ?? ""); }, []);
  useEffect(() => { if (token) void load(); }, [token, load]);
  // Refresh pipeline runs while a stage is running, so progress shows without reloading.
  const live = runs.some((r) => r.status === "running");
  useEffect(() => {
    if (!token || !live) return;
    const t = setInterval(() => { call("/runs").then(setRuns).catch(() => {}); }, 10000);
    return () => clearInterval(t);
  }, [token, live, call]);
  const byRun = [...new Set(runs.map((r) => r.run_id))].slice(0, 5).map((id) => runs.filter((r) => r.run_id === id).reverse());
  const act = (p: string, body: unknown, method = "POST") => call(p, { method, body: JSON.stringify(body) }).then(load).catch(() => setErr("Action failed."));
  return (
    <>
      <Kicker>Editors</Kicker>
      <h1>Admin</h1>
      <form onSubmit={(e) => { e.preventDefault(); const t = new FormData(e.currentTarget).get("t") as string; sessionStorage.setItem("weft:admin", t); setToken(t); }}>
        <label className="kicker" htmlFor="t">Admin token</label> <input id="t" name="t" type="password" /> <button>Use</button>
      </form>
      {err && <p role="alert">{err}</p>}
      <hr /><Kicker>Pipeline runs (nightly batch, last 5){live ? " · running, refreshing every 10s" : ""}</Kicker>
      {byRun.map((stages) => (
        <div className="card" key={stages[0].run_id}>
          <Kicker>Run {stages[0].run_id} · started {new Date(stages[0].started_at).toLocaleString()}</Kicker>
          {stages.map((r) => (
            <div className="row" key={r.stage}>
              <b>{r.stage}</b>
              <span className={r.status === "ok" ? "muted" : undefined}>{r.status}</span>
              {r.rows_out != null && <span className="muted">{r.rows_out} rows</span>}
              {r.ended_at && <span className="muted">{Math.round((Date.parse(r.ended_at) - Date.parse(r.started_at)) / 1000)}s</span>}
              {r.error && <code>{r.error}</code>}
            </div>
          ))}
        </div>
      ))}
      {token && runs.length === 0 && <p className="muted">No pipeline runs yet. The first starts about 30 minutes after startup, then daily.</p>}
      <hr /><Kicker>Stories. Public stories appear on the site; the rest return 404.</Kicker>
      {stories.map((s) => (
        <div className="row" key={s.id}>
          <label><input type="checkbox" checked={s.public} onChange={(e) => act(`/stories/${s.id}/public`, { public: e.target.checked }, "PUT")} /> public</label>
          <b>{s.title}</b><span className="muted">{s.beat_id}</span>
        </div>
      ))}
      <hr /><Kicker>Sources. Country decides the perspective a report counts for; changing it re-tags that source's reports.</Kicker>
      {sources.map((s) => (
        <div className="row" key={s.id}>
          <b>{s.name}</b><span className="muted">{s.domain}</span>
          <label>country <input defaultValue={s.country ?? ""} size={3} maxLength={2} aria-label={`Country of ${s.name}`}
            onBlur={(e) => { const v = e.target.value.trim().toUpperCase(); if (v !== (s.country ?? "")) void act(`/sources/${s.id}`, { country: v || null }, "PATCH"); }} /></label>
          {s.country_source && <span className="muted">from {s.country_source}</span>}
          <label><input type="checkbox" checked={!!s.paywalled} onChange={(e) => act(`/sources/${s.id}`, { paywalled: e.target.checked }, "PATCH")} /> paywalled</label>
          <label><input type="checkbox" checked={s.status === "active"} onChange={(e) => act(`/sources/${s.id}`, { status: e.target.checked ? "active" : "rejected" }, "PATCH")} /> active</label>
          <span className="muted">{s.last_report_at ? `last report ${new Date(s.last_report_at).toLocaleString()}` : "no reports yet"}</span>
        </div>
      ))}
      <hr /><Kicker>Review sample (optional, never blocks publishing)</Kicker>
      {review?.open.map((i) => (
        <div className="card" key={i.id}>
          <Kicker>{i.kind}</Kicker>
          <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{JSON.stringify(i.payload, null, 1)}</pre>
          <div className="row">
            {["good", "bad"].map((r) => <button key={r} onClick={() => act(`/review/${encodeURIComponent(i.id)}`, { rating: r, reviewer: "editor" })}>{r}</button>)}
          </div>
        </div>
      ))}
      {review && review.open.length === 0 && <p className="muted">Nothing to review.</p>}
      <hr /><Kicker>Reader reports</Kicker>
      {problems.map((p) => (
        <div className="card" key={p.id}>
          <Kicker>{p.kind} {p.ref_id ?? ""}</Kicker><p>{p.message}</p>
          <button onClick={() => act(`/reader-reports/${p.id}/resolve`, { resolution: "reviewed" })}>Resolve</button>
        </div>
      ))}
      {problems.length === 0 && <p className="muted">No open reports.</p>}
    </>
  );
}
