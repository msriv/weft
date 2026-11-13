import { perspectiveName } from "@/lib/format";
import type { EventPage } from "@/lib/types";

/** Claims as rows, outlets as columns grouped by the country they report from. A filled cell
 * links to the report and shows the outlet's own sentence. Coverage only: an empty cell means
 * Weft found no sentence from that outlet in this claim group, nothing more. */
export default function ClaimMatrix({ e }: { e: EventPage }) {
  const cols = Object.entries(e.perspectives).flatMap(([p, reps]) => {
    const outlets = new Map<string, string[]>();
    for (const r of reps) outlets.set(r.source.name, [...(outlets.get(r.source.name) ?? []), r.id]);
    return [...outlets.entries()].map(([name, ids]) => ({ p, name, ids: new Set(ids) }));
  });
  const outletOf = new Map(Object.values(e.perspectives).flat().map((r) => [r.id, r.source.name]));
  const groups = e.claim_groups.filter((g) => g.claims?.length);
  if (!groups.length || !cols.length) return <p className="muted">No claims extracted for this event yet.</p>;
  const spans = cols.reduce<{ p: string; n: number }[]>((a, c) => {
    if (a.length && a[a.length - 1].p === c.p) a[a.length - 1].n++; else a.push({ p: c.p, n: 1 });
    return a;
  }, []);
  const numbers = (e.figures ?? []).filter((f) => f.kind === "number");
  const quotes = (e.figures ?? []).filter((f) => f.kind === "quote");
  const bySpeaker = new Map<string, typeof quotes>();
  for (const q of quotes) bySpeaker.set(q.speaker ?? "Speaker not named", [...(bySpeaker.get(q.speaker ?? "Speaker not named") ?? []), q]);
  return (
    <>
      <div style={{ overflowX: "auto" }}>
        <table className="matrix" style={{ borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr><th />{spans.map((s) => <th key={s.p} colSpan={s.n} scope="colgroup">Outlets from {perspectiveName(s.p)}</th>)}</tr>
            <tr><th scope="col">Claim group</th>{cols.map((c) => <th key={`${c.p}:${c.name}`} scope="col" className="muted">{c.name}</th>)}</tr>
          </thead>
          <tbody>
            {groups.map((g) => (
              <tr key={g.id} style={{ borderTop: "1px solid var(--hair)" }}>
                <th scope="row" style={{ textAlign: "left", fontWeight: 400, maxWidth: 320 }}>{g.label}</th>
                {cols.map((c) => {
                  const hit = g.claims.find((x) => c.ids.has(x.report_id));
                  return (
                    <td key={`${c.p}:${c.name}`} style={{ textAlign: "center", padding: 4 }}>
                      {hit ? <a href={`/nodes/${hit.report_id}`} title={hit.text} aria-label={`${c.name}: ${hit.text}`}>●</a> : <span className="muted" aria-label={`No sentence from ${c.name}`}>·</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {numbers.length > 0 && (
        <>
          <h3>Figures</h3>
          <table style={{ fontSize: 13 }}>
            <thead><tr><th scope="col">Figure</th><th scope="col">Quantity</th><th scope="col">Outlet</th><th scope="col">Text</th></tr></thead>
            <tbody>{numbers.map((f) => (
              <tr key={f.id}><td>{f.value}{f.unit ? ` ${f.unit}` : ""}</td><td>{f.quantity ?? ""}</td><td>{outletOf.get(f.report_id) ?? ""}</td><td><a href={`/nodes/${f.report_id}`}>{f.text}</a></td></tr>
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
              {qs.map((q) => <blockquote key={q.id} style={{ margin: "4px 0" }}>{q.text} <a className="muted" href={`/nodes/${q.report_id}`}>{outletOf.get(q.report_id) ?? "report"}</a></blockquote>)}
            </div>
          ))}
        </>
      )}
    </>
  );
}
