import Link from "next/link";
import { notFound } from "next/navigation";
import { AnomalyCard, IssuerTag, Kicker, SourceTag } from "@/components/bits";
import ReportProblem from "@/components/ReportProblem";
import { api } from "@/lib/api";
import { day, perspectiveName } from "@/lib/format";
import type { EventPage } from "@/lib/types";

export default async function Event({ params }: { params: Promise<{ id: string; eventId: string }> }) {
  const { id, eventId } = await params;
  const e = await api<EventPage>(`/v1/events/${eventId}`);
  if (!e) notFound();
  const sv = e.short_version;
  const label = Object.fromEntries(e.claim_groups.map((g) => [g.id, g.label]));
  return (
    <>
      <Link href={`/s/${id}`} className="muted">← Back to the story</Link>
      <Kicker>Event · {day(e.event.first_seen)} · {e.event.perspectives.length} perspectives · {e.event.reports} reports</Kicker>
      <h1>{e.event.label ?? "Event"}</h1>
      {e.event.label_source && <p className="muted">Headline from {e.event.label_source}</p>}
      {sv && (
        <div className="grid g2" style={{ marginTop: 16 }}>
          <div className="card"><Kicker>Reported by all perspectives</Kicker>{sv.reported_by_all.map((g) => <p key={g}>{label[g]}</p>)}{!sv.reported_by_all.length && <p className="muted">None yet.</p>}</div>
          <div className="card"><Kicker anomaly>Reports conflict on</Kicker>{sv.reports_conflict_on.map((p, i) => <p key={i}>{p.map((g) => label[g]).join(" — versus — ")}</p>)}{!sv.reports_conflict_on.length && <p className="muted">None recorded.</p>}</div>
          <div className="card"><Kicker>No source has published</Kicker>{sv.no_source_published.length ? <p>From {sv.no_source_published.map(perspectiveName).join(", ")}</p> : null}{sv.untracked?.length ? <p className="muted">Weft tracks no source from {sv.untracked.map(perspectiveName).join(", ")}.</p> : null}{!sv.no_source_published.length && !sv.untracked?.length && <p className="muted">Every party has published.</p>}</div>
        </div>
      )}
      <hr />
      <Kicker>How each side told it</Kicker>
      <div className="grid g2">
        {Object.entries(e.perspectives).map(([p, reps]) => (
          <section className="card" key={p} aria-label={perspectiveName(p)}>
            <h3>{perspectiveName(p)}</h3>
            <div className="muted">{reps.length} reports</div>
            <Kicker>Headline from {e.voices[p]?.headline_source ?? "one outlet"}{reps[0]?.lang && reps[0].lang !== "en" ? " · translated" : ""}</Kicker>
            <p>{e.voices[p]?.headline}</p>
            {e.voices[p]?.words.length ? <><Kicker>Words they use</Kicker><p>{e.voices[p].words.join(", ")}</p></> : null}
            {reps.map((r) => (
              <div key={r.id} style={{ borderTop: "1px solid var(--hair)", padding: "8px 0" }}>
                <a href={r.url} rel="noopener noreferrer">{r.title}</a> <span className="pill">{r.type}</span>
                <div><SourceTag s={r.source} /></div>
                <p className="muted" style={{ fontSize: 13 }}>{r.summary}{r.lang && r.lang !== "en" && " (translated summary — show original)"}</p>
              </div>
            ))}
          </section>
        ))}
      </div>
      {e.documents.length > 0 && <><hr /><Kicker>Official documents</Kicker>
        {e.documents.map((d) => <div className="card" key={d.id}><Link href={`/d/${d.id}`}>{d.title}</Link> {d.issuer && <IssuerTag i={d.issuer} />}</div>)}</>}
      <hr />
      <Kicker anomaly>Anomalies on this event</Kicker>
      {e.anomalies.map((a) => <AnomalyCard key={a.id} a={a} />)}
      {!e.anomalies.length && <p className="muted">None.</p>}
      <ReportProblem refId={eventId} kind="grouping" label="Report a problem with this grouping" />
    </>
  );
}
