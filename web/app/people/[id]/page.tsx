import Link from "next/link";
import { notFound } from "next/navigation";
import { Kicker } from "@/components/bits";
import { api } from "@/lib/api";
import { day } from "@/lib/format";

type Actor = {
  actor: { id: string; name: string; role: string | null; wikidata_id: string | null };
  statements: { id: string; document_id: string; text: string; title: string; published_at: string | null; story_id: string }[];
  reported_as: { report_id: string; quote: string; event_id: string }[];
};

export default async function Person({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const a = await api<Actor>(`/v1/actors/${id}`);
  if (!a) notFound();
  return (
    <>
      <Kicker>Person · {a.actor.role ?? "public role not stated"}</Kicker>
      <h1>{a.actor.name}</h1>
      <p className="muted">Shown for statements made in official proceedings and releases, in their public role.</p>
      <hr />
      <Kicker>Statements in official documents</Kicker>
      {a.statements.map((s) => (
        <div className="card" key={s.id}>
          <div className="kicker">{day(s.published_at)} · <Link href={`/d/${s.document_id}`}>{s.title}</Link></div>
          <p>“{s.text}”</p>
        </div>
      ))}
      <hr />
      <Kicker>How these statements were reported</Kicker>
      {a.reported_as.length ? a.reported_as.map((q) => (
        <div className="card" key={q.report_id + q.quote}><p>“{q.quote}”</p><Link href={`/nodes/${q.report_id}`}>The report</Link></div>
      )) : <p className="muted">No report in our index quotes this person yet.</p>}
    </>
  );
}
