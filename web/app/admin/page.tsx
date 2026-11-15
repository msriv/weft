"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Kicker } from "@/components/bits";
import { adminHeaders } from "@/lib/account";

type Story = { id: string; beat_id: string; title: string; public: boolean };
type Item = { id: string; kind: string; payload: Record<string, unknown> };
type Problem = { id: number; kind: string; ref_id: string | null; message: string };
type Src = { id: string; name: string; domain: string; country: string | null; country_source: string | null; paywalled: number; status: string; rejected_reason: string | null; last_report_at: string | null };
type Beat = { id: string; name: string; patterns: string[]; exclude: string[]; groups: Record<string, string>; edited: number | null };
type Maybe = { report_id: string; beat_id: string; score: number; title: string | null; url: string | null };
type Unplaced = { id: string; title: string | null; url: string | null; source_id: string; fetched_at: string };
type Status = {
  as_of: string;
  ingest: { state: string; stored: { last_hour: number; last_day: number }; newest_report_at: string | null };
  per_beat_today: { beat: string; reports: number }[];
  nightly: { state: string; stages: { stage: string; last_start: string }[] };
  sources: { active: number; silent: number; silent_days: number; silent_ids: string[] };
  graph: { nodes: number; limit: number | null };
  model_spend: { today: number; cap: number } | null; queue: unknown | null;
};
const STATE: Record<string, string> = { ok: "Working", slow: "Slow", stopped: "Stopped" };
const PAGE = 50;
type Run = { run_id: string; stage: string; started_at: string; ended_at: string | null; rows_out: number | null; status: string; error: string | null };

type Clean = { run_id: string; rule: string; rule_version: number; mode: string; matched: number; changed: number; status: string; started_at: string; note: string | null };

export default function Admin() {
  const [auth, setAuth] = useState<Record<string, string> | null>(null);
  const [log, setLog] = useState<{ at: string; actor: string; method: string; route: string; target: string }[]>([]);
  const [stories, setStories] = useState<Story[]>([]);
  const [review, setReview] = useState<{ open: Item[] } | null>(null);
  const [problems, setProblems] = useState<Problem[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [sources, setSources] = useState<Src[]>([]);
  const [beats, setBeats] = useState<Beat[]>([]);
  const [unplaced, setUnplaced] = useState<Unplaced[]>([]);
  const [maybes, setMaybes] = useState<Maybe[]>([]);
  const [clean, setClean] = useState<Clean[]>([]);
  const [err, setErr] = useState("");
  const [errs, setErrs] = useState<Record<string, boolean>>({});
  const [status, setStatus] = useState<Status | null>(null);
  const [srcQ, setSrcQ] = useState({ q: "", status: "", offset: 0 });
  const [srcTotal, setSrcTotal] = useState(0);
  const call = useCallback(async (path: string, init: RequestInit = {}) => {
    const r = await fetch(`/api/admin${path}`, { ...init, headers: { "Content-Type": "application/json", ...auth } });
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  }, [auth]);
  // Each section loads on its own: one failing endpoint shows its own error and retry.
  const loaders = useMemo<Record<string, () => Promise<void>>>(() => ({
    status: async () => setStatus(await call("/status")),
    stories: async () => setStories(await call("/stories")),
    review: async () => setReview(await call("/review")),
    problems: async () => setProblems(await call("/reader-reports")),
    runs: async () => setRuns(await call("/runs")),
    sources: async () => {
      const p = new URLSearchParams({ limit: String(PAGE), offset: String(srcQ.offset) });
      if (srcQ.q) p.set("q", srcQ.q);
      if (srcQ.status) p.set("status", srcQ.status);
      const r = await fetch(`/api/admin/sources?${p}`, { headers: { "Content-Type": "application/json", ...auth } });
      if (!r.ok) throw new Error(`${r.status}`);
      setSrcTotal(Number(r.headers.get("X-Total-Count") ?? 0));
      setSources(await r.json());
    },
    beats: async () => setBeats(await call("/beats")),
    unplaced: async () => setUnplaced(await call("/unplaced")),
    maybes: async () => setMaybes(await call("/beat-maybes")),
    log: async () => setLog(await call("/log")),
    clean: async () => setClean(await call("/autoclean")),
  }), [call, auth, srcQ]);
  const loadOne = useCallback((k: string) => loaders[k]().then(() => setErrs((e) => ({ ...e, [k]: false }))).catch(() => setErrs((e) => ({ ...e, [k]: true }))), [loaders]);
  const load = useCallback(async () => { setErr(""); await Promise.all(Object.keys(loaders).map(loadOne)); }, [loaders, loadOne]);
  const Retry = ({ k }: { k: string }) => errs[k] ? <p role="alert">Could not load this section. <button className="small" onClick={() => void loadOne(k)}>Retry</button></p> : null;
  useEffect(() => { void adminHeaders().then(setAuth); }, []);
  useEffect(() => { if (auth) void load(); }, [auth, load]);
  // Refresh pipeline runs while a stage is running, so progress shows without reloading.
  const live = runs.some((r) => r.status === "running");
  useEffect(() => {
    if (!auth || !live) return;
    const t = setInterval(() => { call("/runs").then(setRuns).catch(() => {}); }, 10000);
    return () => clearInterval(t);
  }, [auth, live, call]);
  const byRun = [...new Set(runs.map((r) => r.run_id))].slice(0, 5).map((id) => runs.filter((r) => r.run_id === id).reverse());
  const act = (p: string, body: unknown, method = "POST") => call(p, { method, body: JSON.stringify(body) }).then(load).catch(() => setErr("Action failed."));
  return (
    <>
      <Kicker>Editors</Kicker>
      <h1>Admin</h1>
      {!auth && <p>Admin needs a signed-in editor account. <Link href="/welcome">Sign in</Link>, then reload.</p>}
      {err && <p role="alert">{err}</p>}
      <hr /><Kicker>Status</Kicker>
      <Retry k="status" />
      {status && (
        <div className="grid g2">
          <div className="card">
            <Kicker>Ingest · {STATE[status.ingest.state] ?? status.ingest.state}</Kicker>
            <p className="m0">{status.ingest.stored.last_hour} reports stored in the last hour, {status.ingest.stored.last_day} in the last day.</p>
            <p className="muted fs13 m0">{status.ingest.newest_report_at ? `Newest stored ${new Date(status.ingest.newest_report_at).toLocaleString()}` : "No report stored yet"}</p>
            <p className="muted fs13 m0">{status.per_beat_today.length ? status.per_beat_today.map((b) => `${b.beat}: ${b.reports}`).join(" · ") : "Nothing stored today"} (unplaced = matched no beat)</p>
          </div>
          <div className="card">
            <Kicker>Nightly stages · {STATE[status.nightly.state] ?? status.nightly.state}</Kicker>
            {status.nightly.stages.length ? status.nightly.stages.map((s) => <div className="row" key={s.stage}><b>{s.stage}</b><span className="muted">{new Date(s.last_start).toLocaleString()}</span></div>) : <p className="muted m0">No stage has run yet.</p>}
          </div>
          <div className="card">
            <Kicker>Sources</Kicker>
            <p className="m0">{status.sources.active} active, {status.sources.silent} with no stored report for {status.sources.silent_days} days.</p>
            {status.sources.silent_ids.length > 0 && <p className="muted fs13 m0">{status.sources.silent_ids.join(", ")}</p>}
          </div>
          <div className="card">
            <Kicker>Graph and model</Kicker>
            <p className="m0">{status.graph.nodes.toLocaleString()} nodes{status.graph.limit ? ` of ${status.graph.limit.toLocaleString()}` : ""}.</p>
            <p className="muted fs13 m0">Model spend today: {status.model_spend ? `${status.model_spend.today} of ${status.model_spend.cap}` : "not available"}. Queue depth: {status.queue ? "see monitoring" : "not available"}.</p>
          </div>
        </div>
      )}
      <hr /><Kicker>Pipeline runs (nightly batch, last 5){live ? " · running, refreshing every 10s" : ""}</Kicker>
      <Retry k="runs" />
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
      {auth && runs.length === 0 && <p className="muted">No pipeline runs yet. The first starts about 30 minutes after startup, then daily.</p>}
      <hr /><Kicker>Autoclean (last runs). A rule in dry_run only counts; it changes nothing.</Kicker>
      {clean.slice(0, 30).map((r) => (
        <div className="row" key={`${r.run_id}:${r.rule}`}>
          <b>{r.rule}</b> <span className="muted">v{r.rule_version}</span>
          <span className={r.status === "ok" || r.status === "dry_run" ? "muted" : undefined}>{r.status}</span>
          <span className="muted">{r.mode}</span>
          <span>{r.matched} matched · {r.changed} changed</span>
          <span className="muted">{new Date(r.started_at).toLocaleString()}</span>
          {r.note && <code>{r.note}</code>}
        </div>
      ))}
      {auth && clean.length === 0 && <p className="muted">No autoclean runs yet.</p>}
      <hr /><Kicker>Stories. Public stories appear on the site; the rest return 404.</Kicker>
      <Retry k="stories" />
      {stories.map((s) => (
        <div className="row" key={s.id}>
          <label><input type="checkbox" checked={s.public} onChange={(e) => { if (window.confirm(e.target.checked ? `Publish "${s.title}"? It becomes visible to every reader.` : `Unpublish "${s.title}"? Readers will get a 404.`)) void act(`/stories/${s.id}/public`, { public: e.target.checked }, "PUT"); }} /> public</label>
          <b>{s.title}</b><span className="muted">{s.beat_id}</span>
        </div>
      ))}
      <hr /><Kicker>Sources. Country decides the perspective a report counts for; changing it re-tags that source's reports.</Kicker>
      <form className="row" onSubmit={(e) => { e.preventDefault(); const f = e.currentTarget; void act("/sources", { url: new FormData(f).get("url") }).then(() => f.reset()); }}>
        <label htmlFor="add-src" className="muted">Add an outlet (checked and registered on the next discovery run, within the hour)</label>
        <input id="add-src" name="url" placeholder="https://example.com" required /> <button>Add</button>
      </form>
      <form className="row" role="search" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); setSrcQ({ q: String(f.get("q") ?? ""), status: String(f.get("status") ?? ""), offset: 0 }); }}>
        <label htmlFor="src-q" className="muted">Find by name or domain</label>
        <input id="src-q" name="q" defaultValue={srcQ.q} />
        <label htmlFor="src-status" className="muted">Status</label>
        <select id="src-status" name="status" defaultValue={srcQ.status}><option value="">Any</option><option value="active">Active</option><option value="rejected">Rejected</option></select>
        <button>Search</button>
      </form>
      <Retry k="sources" />
      <p className="muted fs13">{srcTotal ? `${srcQ.offset + 1} to ${Math.min(srcQ.offset + PAGE, srcTotal)} of ${srcTotal}` : "No sources match."}</p>
      {sources.map((s) => (
        <div className="row" key={s.id}>
          <b>{s.name}</b><span className="muted">{s.domain} · id <code>{s.id}</code></span>
          <label>country <input defaultValue={s.country ?? ""} size={3} maxLength={2} aria-label={`Country of ${s.name}`}
            onBlur={(e) => { const v = e.target.value.trim().toUpperCase(); if (v !== (s.country ?? "")) void act(`/sources/${s.id}`, { country: v || null }, "PATCH"); }} /></label>
          {s.country_source && <span className="muted">from {s.country_source}</span>}
          <label><input type="checkbox" checked={!!s.paywalled} onChange={(e) => act(`/sources/${s.id}`, { paywalled: e.target.checked }, "PATCH")} /> paywalled</label>
          <label><input type="checkbox" checked={s.status === "active"} onChange={(e) => act(`/sources/${s.id}`, { status: e.target.checked ? "active" : "rejected" }, "PATCH")} /> active</label>
          {s.status === "rejected" && s.rejected_reason && <span className="muted">rejected: {s.rejected_reason}</span>}
          <span className="muted">{s.last_report_at ? `last report ${new Date(s.last_report_at).toLocaleString()}` : "no reports yet"}</span>
        </div>
      ))}
      <div className="row">
        <button className="small" disabled={srcQ.offset === 0} onClick={() => setSrcQ({ ...srcQ, offset: Math.max(0, srcQ.offset - PAGE) })}>Previous</button>
        <button className="small" disabled={srcQ.offset + PAGE >= srcTotal} onClick={() => setSrcQ({ ...srcQ, offset: srcQ.offset + PAGE })}>Next</button>
      </div>
      <hr /><Kicker>Beats. A report joins a beat when any pattern matches its title or lede and no exclusion does. One regex per line; applies to new reports.</Kicker>
      <Retry k="beats" />
      {beats.map((b) => (
        <form className="card" key={b.id} onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          const lines = (k: string) => String(f.get(k) ?? "").split("\n");
          const groups = Object.fromEntries(lines("groups").map((l) => l.split("=").map((x) => x.trim())).filter((kv) => kv.length === 2 && kv[0] && kv[1]));
          void act(`/beats/${b.id}`, { patterns: lines("patterns"), exclude: lines("exclude"), groups }, "PUT");
        }}>
          <Kicker>{b.name}{b.edited ? " · edited" : ""}</Kicker>
          <label className="muted" htmlFor={`p-${b.id}`}>Match any</label>
          <textarea id={`p-${b.id}`} name="patterns" rows={3} style={{ width: "100%" }} defaultValue={b.patterns.join("\n")} />
          <label className="muted" htmlFor={`x-${b.id}`}>But not</label>
          <textarea id={`x-${b.id}`} name="exclude" rows={2} style={{ width: "100%" }} defaultValue={b.exclude.join("\n")} />
          <label className="muted" htmlFor={`g-${b.id}`}>Outlet groups, one per line as source id = group. Leave empty to group outlets by country. Use this for domestic beats where every outlet shares one country.</label>
          <textarea id={`g-${b.id}`} name="groups" rows={3} style={{ width: "100%" }} defaultValue={Object.entries(b.groups ?? {}).map(([k, v]) => `${k} = ${v}`).join("\n")} />
          <button>Save</button>
        </form>
      ))}
      <hr /><Kicker>Unplaced reports (newest {unplaced.length}). These matched no beat; use them to tune the terms above.</Kicker>
      <Retry k="unplaced" />
      {unplaced.map((r) => (
        <div className="row" key={r.id}>
          {r.url ? <a href={r.url} target="_blank" rel="noreferrer">{r.title ?? r.url}</a> : <span>{r.title ?? r.id}</span>}
          <span className="muted">{r.source_id}</span>
        </div>
      ))}
      <hr /><Kicker>Maybe on a beat ({maybes.length}). Your answers tune beat relevance; they never move a report.</Kicker>
      <Retry k="maybes" />
      {maybes.map((m) => (
        <div className="row" key={`${m.report_id}:${m.beat_id}`}>
          {m.url ? <a href={m.url} target="_blank" rel="noreferrer">{m.title ?? m.url}</a> : <span>{m.title ?? m.report_id}</span>}
          <span className="muted">{m.beat_id} · {m.score.toFixed(2)}</span>
          {[true, false].map((on) => <button key={String(on)} onClick={() => act(`/beat-maybes/${encodeURIComponent(m.report_id)}`, { beat_id: m.beat_id, on_beat: on })}>{on ? "On beat" : "Off beat"}</button>)}
        </div>
      ))}
      <hr /><Kicker>Review sample (optional, never blocks publishing)</Kicker>
      <Retry k="review" />
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
      <hr /><Kicker>Admin log (last 50 changes)</Kicker>
      <Retry k="log" />
      {log.map((l, i) => (
        <div className="row" key={i}>
          <span className="muted">{new Date(l.at).toLocaleString()}</span><b>{l.actor}</b>
          <span>{l.method} {l.route}</span><code>{l.target}</code>
        </div>
      ))}
      {log.length === 0 && <p className="muted">No changes yet.</p>}
      <hr /><Kicker>Reader reports</Kicker>
      <Retry k="problems" />
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
