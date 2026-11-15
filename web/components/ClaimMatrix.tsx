"use client";
import Link from "next/link";
import { useState } from "react";
import { day, perspectiveName } from "@/lib/format";
import { columns, coverage, filterRows, rows, type Filter } from "@/lib/matrix";
import type { EventPage } from "@/lib/types";

const FILTERS: [Filter, string][] = [["all", "All"], ["conflicts", "Conflicts"], ["single", "One perspective only"]];

/** Claims as rows, outlets as columns grouped by the country they report from. A filled square
 * means the outlet's own sentence is in that claim group; open it to read it. An empty square
 * means Weft found no sentence from that outlet in this group, nothing more. */
export default function ClaimMatrix({ e }: { e: EventPage }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [open, setOpen] = useState<{ row: string; col: string } | null>(null);
  const [hl, setHl] = useState<{ row?: string; col?: string }>({});
  const cols = columns(e);
  const all = rows(e, cols);
  if (!all.length || !cols.length) return <p className="muted">No claims extracted for this event yet.</p>;
  const shown = filterRows(all, filter);
  const total = Object.keys(e.perspectives).length;
  const reports = new Map(Object.values(e.perspectives).flat().map((r) => [r.id, r]));
  const outletOf = (id: string) => reports.get(id)?.source.name ?? "";
  const spans = cols.reduce<{ p: string; n: number }[]>((a, c) => {
    if (a.length && a[a.length - 1].p === c.p) a[a.length - 1].n++; else a.push({ p: c.p, n: 1 });
    return a;
  }, []);
  const first = new Set(spans.map((s) => cols.findIndex((c) => c.p === s.p)));
  const numbers = (e.figures ?? []).filter((f) => f.kind === "number");
  const quotes = (e.figures ?? []).filter((f) => f.kind === "quote");
  const bySpeaker = new Map<string, typeof quotes>();
  for (const q of quotes) bySpeaker.set(q.speaker ?? "Speaker not named", [...(bySpeaker.get(q.speaker ?? "Speaker not named") ?? []), q]);
  const sel = open ? { row: all.find((r) => r.id === open.row), col: cols.find((c) => c.key === open.col) } : null;
  const hit = sel?.row && sel.col ? sel.row.hits.get(sel.col.key) : null;
  const rep = hit ? reports.get(hit.report_id) : null;

  return (
    <div onKeyDown={(ev) => ev.key === "Escape" && setOpen(null)}>
      <div className="row mb12" role="group" aria-label="Filter claim groups">
        {FILTERS.map(([k, l]) => <button key={k} className="small" aria-pressed={filter === k} onClick={() => setFilter(k)}>{l}</button>)}
      </div>
      <div className="matrix-wrap">
        <table className="matrix">
          <thead>
            <tr>
              <th className="sticky-col" />
              {spans.map((s) => <th key={s.p} colSpan={s.n} scope="colgroup" className="perspective-head">{perspectiveName(s.p)}</th>)}
              <th scope="col" className="muted">Carried by</th>
            </tr>
            <tr>
              <th scope="col" className="sticky-col">Claim group</th>
              {cols.map((c, i) => (
                <th key={c.key} scope="col" className={`col-head${first.has(i) ? " divider" : ""}${hl.col === c.key ? " hl" : ""}`} title={c.name}><span>{c.name}</span></th>
              ))}
              <th />
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.id} className={`${r.conflict ? "conflict-row " : ""}${hl.row === r.id ? "hl" : ""}`}>
                <th scope="row" className="sticky-col">{r.label}{r.conflict && <span className="pill anomaly mark-conflict">Conflict</span>}</th>
                {cols.map((c, i) => {
                  const h = r.hits.get(c.key);
                  const on = open?.row === r.id && open.col === c.key;
                  return (
                    <td key={c.key} className={`${first.has(i) ? "divider " : ""}${hl.col === c.key ? "hl" : ""}`}>
                      {h ? (
                        <button
                          className={`cell on${on ? " sel" : ""}`} aria-expanded={on} aria-label={`${c.name}: sentence found in "${r.label}". Open it.`}
                          onClick={() => setOpen(on ? null : { row: r.id, col: c.key })}
                          onMouseEnter={() => { setOpen({ row: r.id, col: c.key }); setHl({ row: r.id, col: c.key }); }}
                          onFocus={() => { setOpen({ row: r.id, col: c.key }); setHl({ row: r.id, col: c.key }); }}
                          onBlur={() => setHl({})} onMouseLeave={() => setHl({})}
                        />
                      ) : (
                        <span className="cell off" role="img" aria-label={`No sentence found from ${c.name}`} />
                      )}
                    </td>
                  );
                })}
                <td className="muted fs12">{coverage(r, total)}</td>
              </tr>
            ))}
            {!shown.length && <tr><td colSpan={cols.length + 2} className="muted">No claim group matches this filter.</td></tr>}
          </tbody>
        </table>
      </div>
      <p className="muted fs12">Filled: the outlet's own sentence is in this claim group. Empty: Weft found no sentence from that outlet in it.</p>
      {sel?.col && hit && rep && (
        <div className="card" role="region" aria-label="Sentence behind the selected cell" aria-live="polite">
          <div className="row"><b>{sel.col.name}</b><span className="muted fs13">{rep.published_at ? day(rep.published_at) : "Publish time not recorded"}</span><button className="small" onClick={() => setOpen(null)}>Close</button></div>
          <blockquote>{hit.text}</blockquote>
          <div className="row fs13">
            <a href={rep.url} rel="noopener noreferrer">Source article</a>
            <Link href={`/nodes/${rep.id}`}>Evidence page</Link>
          </div>
        </div>
      )}
      {numbers.length > 0 && (
        <>
          <h3>Figures</h3>
          <table className="fs13">
            <thead><tr><th scope="col">Figure</th><th scope="col">Quantity</th><th scope="col">Outlet</th><th scope="col">Text</th></tr></thead>
            <tbody>{numbers.map((f) => (
              <tr key={f.id}><td>{f.value}{f.unit ? ` ${f.unit}` : ""}</td><td>{f.quantity ?? ""}</td><td>{outletOf(f.report_id)}</td><td><Link href={`/nodes/${f.report_id}`}>{f.text}</Link></td></tr>
            ))}</tbody>
          </table>
        </>
      )}
      {bySpeaker.size > 0 && (
        <>
          <h3>Quotes by speaker</h3>
          {[...bySpeaker.entries()].map(([who, qs]) => (
            <div key={who}>
              <b>{who}</b>
              {qs.map((q) => <blockquote key={q.id} className="my4">{q.text} <Link className="muted" href={`/nodes/${q.report_id}`}>{outletOf(q.report_id) || "report"}</Link></blockquote>)}
            </div>
          ))}
        </>
      )}
    </div>
  );
}
