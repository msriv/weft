"use client";
import { useCallback, useEffect, useState } from "react";
import { Kicker } from "@/components/bits";

type Story = { id: string; beat_id: string; title: string; public: boolean };
type Item = { id: string; kind: string; payload: Record<string, unknown> };
type Problem = { id: number; kind: string; ref_id: string | null; message: string };

export default function Admin() {
  const [token, setToken] = useState("");
  const [stories, setStories] = useState<Story[]>([]);
  const [review, setReview] = useState<{ open: Item[] } | null>(null);
  const [problems, setProblems] = useState<Problem[]>([]);
  const [err, setErr] = useState("");
  const call = useCallback(async (path: string, init: RequestInit = {}) => {
    const r = await fetch(`/api/admin${path}`, { ...init, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` } });
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  }, [token]);
  const load = useCallback(async () => {
    try {
      setErr("");
      setStories(await call("/stories")); setReview(await call("/review")); setProblems(await call("/reader-reports"));
    } catch { setErr("Could not load. Check the token."); }
  }, [call]);
  useEffect(() => { setToken(sessionStorage.getItem("weft:admin") ?? ""); }, []);
  useEffect(() => { if (token) void load(); }, [token, load]);
  const act = (p: string, body: unknown, method = "POST") => call(p, { method, body: JSON.stringify(body) }).then(load).catch(() => setErr("Action failed."));
  return (
    <>
      <Kicker>Editors</Kicker>
      <h1>Admin</h1>
      <form onSubmit={(e) => { e.preventDefault(); const t = new FormData(e.currentTarget).get("t") as string; sessionStorage.setItem("weft:admin", t); setToken(t); }}>
        <label className="kicker" htmlFor="t">Admin token</label> <input id="t" name="t" type="password" /> <button>Use</button>
      </form>
      {err && <p role="alert">{err}</p>}
      <hr /><Kicker>Stories. Public stories appear on the site; the rest return 404.</Kicker>
      {stories.map((s) => (
        <div className="row" key={s.id}>
          <label><input type="checkbox" checked={s.public} onChange={(e) => act(`/stories/${s.id}/public`, { public: e.target.checked }, "PUT")} /> public</label>
          <b>{s.title}</b><span className="muted">{s.beat_id}</span>
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
