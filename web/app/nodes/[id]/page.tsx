import { notFound } from "next/navigation";
import { AnomalyDetail, Kicker } from "@/components/bits";
import { api } from "@/lib/api";
import { perspectiveName } from "@/lib/format";

type Link = { label: string; url?: string; id?: string; source?: string; quote?: string };
type N = { kind: string; node: Record<string, unknown>; links: Link[] };

function Evidence({ links }: { links: Link[] }) {
  return (
    <ul>
      {links.map((l, i) => (
        <li key={i}>
          {l.url ? <a href={l.url} rel="noopener noreferrer">{l.label} ↗</a> : <a href={`/nodes/${l.id}`}>{l.label}</a>}
          {l.quote && <blockquote style={{ margin: "4px 0" }}>{l.quote}</blockquote>}
        </li>
      ))}
    </ul>
  );
}

export default async function NodePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const n = await api<N>(`/v1/nodes/${id}`);
  if (!n) notFound();
  const x = n.node;
  const detail = (x.detail ?? {}) as Record<string, unknown>;
  const ids = (k: string) => new Set(Array.isArray(detail[k]) ? (detail[k] as string[]) : []);
  const carrying = ids("carrying");
  const without = ids("perspective_reports");
  const omission = x.rule === "omission" && (carrying.size > 0 || without.size > 0);
  return (
    <>
      <Kicker>{n.kind.replace("_", " ")}</Kicker>
      <h1>{String(x.title ?? x.summary ?? x.label ?? x.text ?? x.id)}</h1>
      {n.kind === "anomaly" && (
        <>
          <p>
            Fired by rule <b>{String(x.rule)}</b>, version {String(x.rule_version)}. No AI model decided this: the rule
            compares reports with other reports. What it looked at and the evidence it counted are below.
          </p>
          <AnomalyDetail a={{ rule: String(x.rule), detail }} max={40} />
          {omission ? (
            <>
              <h3>Reports carrying this claim group</h3>
              <Evidence links={n.links.filter((l) => l.id && carrying.has(l.id))} />
              <h3>Reports from {perspectiveName(String(detail.perspective ?? (x.inputs as Record<string, unknown>)?.perspective ?? ""))} that do not</h3>
              <Evidence links={n.links.filter((l) => l.id && without.has(l.id))} />
            </>
          ) : (
            <>
              <h3>Evidence</h3>
              <Evidence links={n.links} />
            </>
          )}
          <details>
            <summary className="muted">Thresholds the rule used</summary>
            <pre className="card" style={{ overflow: "auto", fontSize: 12 }}>{JSON.stringify(x.inputs ?? {}, null, 2)}</pre>
          </details>
        </>
      )}
      {n.kind !== "anomaly" && (
        <>
          {x.detail != null && <pre className="card" style={{ overflow: "auto", fontSize: 12 }}>{JSON.stringify(x.detail, null, 2)}</pre>}
          <Evidence links={n.links} />
        </>
      )}
    </>
  );
}
