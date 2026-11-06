import { notFound } from "next/navigation";
import { Kicker } from "@/components/bits";
import { api } from "@/lib/api";

type N = { kind: string; node: Record<string, unknown>; links: { label: string; url?: string; id?: string }[] };

export default async function NodePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const n = await api<N>(`/v1/nodes/${id}`);
  if (!n) notFound();
  const x = n.node;
  return (
    <>
      <Kicker>{n.kind.replace("_", " ")}</Kicker>
      <h1>{String(x.title ?? x.summary ?? x.label ?? x.text ?? x.id)}</h1>
      {n.kind === "anomaly" && (
        <p>
          Fired by rule <b>{String(x.rule)}</b>, version {String(x.rule_version)}. No AI model decided this: the rule
          compares reports with other reports. The thresholds it used are below; the evidence it counted is linked.
        </p>
      )}
      <pre className="card" style={{ overflow: "auto", fontSize: 12 }}>{JSON.stringify(x.inputs ?? x.detail ?? {}, null, 2)}</pre>
      {n.links.map((l, i) => (
        <div key={i}>{l.url ? <a href={l.url} rel="noopener noreferrer">{l.label} ↗</a> : <a href={`/nodes/${l.id}`}>{l.label}: {l.id}</a>}</div>
      ))}
    </>
  );
}
