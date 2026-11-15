import { notFound } from "next/navigation";
import Breadcrumbs from "@/components/Breadcrumbs";
import { storyTitle } from "@/lib/crumbs";
import { AnomalyDetail, Kicker } from "@/components/bits";
import { api } from "@/lib/api";
import { Fields, RuleTable } from "@/components/Fields";
import { kindLabel, perspectiveName, ruleName } from "@/lib/format";

type Link = { label: string; url?: string; id?: string; source?: string; quote?: string };
type N = { kind: string; node: Record<string, unknown>; links: Link[] };

function Evidence({ links }: { links: Link[] }) {
  return (
    <ul>
      {links.map((l, i) => (
        <li key={i}>
          {l.url ? <a href={l.url} rel="noopener noreferrer">{l.label} ↗</a> : <a href={`/nodes/${l.id}`}>{l.label}</a>}
          {l.quote && <blockquote className="my4">{l.quote}</blockquote>}
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
  const sid = typeof x.story_id === "string" ? x.story_id : null;
  const eid = typeof x.event_id === "string" ? x.event_id : null;
  const title = sid ? await storyTitle(sid) : null;
  return (
    <>
      {sid && title && <Breadcrumbs items={[{ label: "Stories", href: "/stories" }, { label: title, href: `/s/${sid}` }, ...(eid ? [{ label: "Event", href: `/s/${sid}/e/${eid}` }] : []), { label: "Evidence" }]} />}
      <Kicker>{kindLabel(n.kind)}</Kicker>
      <h1>{String(x.title ?? x.summary ?? x.label ?? x.text ?? x.id)}</h1>
      {n.kind === "anomaly" && (
        <>
          <p>
            Fired by the rule <b>{ruleName(String(x.rule))}</b>, version {String(x.rule_version)}. No AI model decided this: the rule
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
          <h3>Thresholds the rule used</h3>
          <RuleTable rule={String(x.rule)} values={(x.inputs ?? {}) as Record<string, unknown>} />
          <details>
            <summary className="muted">Show raw rule inputs</summary>
            <pre className="card oauto fs12">{JSON.stringify(x.inputs ?? {}, null, 2)}</pre>
          </details>
        </>
      )}
      {n.kind !== "anomaly" && (
        <>
          {x.detail != null && <div className="card"><Fields data={x.detail} /></div>}
          <Evidence links={n.links} />
        </>
      )}
    </>
  );
}
