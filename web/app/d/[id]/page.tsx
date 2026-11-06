import Link from "next/link";
import { notFound } from "next/navigation";
import ReportProblem from "@/components/ReportProblem";
import { IssuerTag, Kicker } from "@/components/bits";
import { api } from "@/lib/api";
import { day } from "@/lib/format";
import type { Issuer } from "@/lib/types";

type Doc = {
  document: { id: string; url: string; kind: string; title: string; summary: string; published_at: string | null; lang: string | null; story_id: string; event_id: string | null };
  issuer: Issuer | null; label: string | null;
  statements: { id: string; actor_id: string; actor: string; role: string | null; text: string; start: number }[];
  event: { id: string; label: string | null } | null;
};

export default async function DocumentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const d = await api<Doc>(`/v1/documents/${id}`);
  if (!d) notFound();
  const speakers = [...new Map(d.statements.map((s) => [s.actor_id, s])).values()];
  return (
    <>
      <Link href={`/s/${d.document.story_id}`} className="muted">← Back to the story</Link>
      <Kicker>Official document · {d.document.kind} · {day(d.document.published_at)}</Kicker>
      <h1>{d.document.title}</h1>
      <div className="row" style={{ margin: "10px 0" }}>{d.issuer && <IssuerTag i={d.issuer} />}</div>
      {d.label && <p>{d.label}</p>}
      <a href={d.document.url} rel="noopener noreferrer">Original document ↗</a>
      <p className="muted">{d.document.summary}</p>
      {d.event && <p>Records: <Link href={`/s/${d.document.story_id}/e/${d.event.id}`}>{d.event.label ?? "event"}</Link></p>}
      <hr />
      <Kicker>Who spoke ({speakers.length})</Kicker>
      <div className="row">{speakers.map((s) => <Link key={s.actor_id} className="pill on" href={`/people/${s.actor_id}`}>{s.actor}{s.role ? ` · ${s.role}` : ""}</Link>)}</div>
      <Kicker>Statements</Kicker>
      {d.statements.map((s) => (
        <div className="card" key={s.id}>
          <div className="kicker">{s.actor} · character {s.start}</div>
          <p>“{s.text}”</p>
        </div>
      ))}
      {!d.statements.length && <p className="muted">No speaker turns were found in this document.</p>}
      <ReportProblem refId={id} kind="other" label="Report a problem with this page" />
    </>
  );
}
