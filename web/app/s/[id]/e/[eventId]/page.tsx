import Link from "next/link";
import { notFound } from "next/navigation";
import { AnomalyCard, IssuerTag, Kicker, SourceTag } from "@/components/bits";
import ClaimMatrix from "@/components/ClaimMatrix";
import Conflict from "@/components/Conflict";
import ReportProblem from "@/components/ReportProblem";
import { api } from "@/lib/api";
import { meta } from "@/lib/meta";
import { day, perspectiveName } from "@/lib/format";
import { plural, type Side } from "@/lib/story";
import type { EventPage } from "@/lib/types";

export async function generateMetadata({ params }: { params: Promise<{ id: string; eventId: string }> }) {
  const p = await params;
  const x = await api<EventPage>(`/v1/events/${p.eventId}`);
  return meta(x?.event.label ?? "Event", "Coverage of one event within a story.");
}

export default async function Event({ params }: { params: Promise<{ id: string; eventId: string }> }) {
  const { id, eventId } = await params;
  const e = await api<EventPage>(`/v1/events/${eventId}`);
  if (!e) notFound();
  const sv = e.short_version;
  const label = Object.fromEntries(e.claim_groups.map((g) => [g.id, g.label]));
  const reports = new Map(Object.values(e.perspectives).flat().map((r) => [r.id, r]));
  const side = (gid: string): Side => {
    const g = e.claim_groups.find((x) => x.id === gid);
    return { claim: g?.label ?? "", perspectives: g?.perspectives ?? [], outlets: [...new Set((g?.claims ?? []).map((c) => reports.get(c.report_id)?.source.name).filter((n): n is string => !!n))].sort() };
  };
  return (
    <>
      <Link href={`/s/${id}`} className="muted">← Back to the story</Link>
      <Kicker>Event · {day(e.event.first_seen)} · {plural(e.event.perspectives.length, "perspective")} · {plural(e.event.reports, "report")}{e.event.outlets != null && e.event.origins != null ? ` · ${plural(e.event.outlets, "outlet")}, ${plural(e.event.origins, "independent text")}` : ""}</Kicker>
      <h1>{e.event.label ?? "Event"}</h1>
      {e.event.label_source && <p className="muted">Headline from {e.event.label_source}</p>}

      <section aria-label="Where accounts differ" className="mt16">
        {e.conflicts.length ? e.conflicts.map((c, i) => c.groups.length >= 2 && <Conflict key={i} a={side(c.groups[0])} b={side(c.groups[1])} href="#claims" linkLabel="See who carries each claim" />)
          : <p className="muted">No conflicting claims recorded for this event.</p>}
        {e.anomalies.length > 0 && (
          <>
            <Kicker anomaly>Anomalies on this event</Kicker>
            {e.anomalies.map((a) => <AnomalyCard key={a.id} a={a} />)}
          </>
        )}
      </section>

      {sv && (
        <div className="grid g2 mt16">
          <div className="card"><Kicker>Reported by all perspectives</Kicker>{sv.reported_by_all.map((g) => <p key={g}>{label[g]}</p>)}{!sv.reported_by_all.length && <p className="muted">None yet.</p>}</div>
          <div className="card"><Kicker>No source has published</Kicker>{sv.no_source_published.length ? <p>From {sv.no_source_published.map(perspectiveName).join(", ")}</p> : null}{sv.untracked?.length ? <p className="muted">Weft tracks no source from {sv.untracked.map(perspectiveName).join(", ")}.</p> : null}{!sv.no_source_published.length && !sv.untracked?.length && <p className="muted">Every party has published.</p>}</div>
        </div>
      )}
      <hr />
      <Kicker>Who carries which claim</Kicker>
      <div id="claims"><ClaimMatrix e={e} /></div>
      <hr />
      <Kicker>How outlets from each country told it</Kicker>
      <p className="muted fs13">Ownership and state-run labels are shown only where they are known and cited. Elsewhere ownership is unverified.</p>
      <div className="grid g2">
        {Object.entries(e.perspectives).map(([p, reps]) => (
          <section className="card" key={p} aria-label={perspectiveName(p)}>
            <h3 className="m0">{perspectiveName(p)}</h3>
            <div className="muted">{plural(reps.length, "report")}</div>
            {e.voices[p]?.headline && <p className="mt8">{e.voices[p].headline} <span className="muted fs12">· headline from {e.voices[p].headline_source ?? "one outlet"}{reps[0]?.lang && reps[0].lang !== "en" ? ", translated" : ""}</span></p>}
            {e.voices[p]?.words.length ? <p className="muted fs13">Words they use: {e.voices[p].words.join(", ")}</p> : null}
            {reps.map((r) => (
              <details key={r.id} className="bt report">
                <summary>
                  <span>{r.source.name}</span> <span className="muted">· {r.title}{r.published_at ? ` · ${day(r.published_at)}` : ""}</span>
                </summary>
                <p className="fs13"><a href={r.url} rel="noopener noreferrer">{r.title}</a> <span className="pill">{r.type}</span></p>
                {r.source.state_run !== "unverified" && <div><SourceTag s={r.source} /></div>}
                {r.source.paywalled && <p className="muted fs12">Paywalled: headline and lede only.</p>}
                <p className="muted fs13">{r.summary}{r.lang && r.lang !== "en" && " (translated summary — show original)"}</p>
              </details>
            ))}
          </section>
        ))}
      </div>
      {e.documents.length > 0 && <><hr /><Kicker>Official documents</Kicker>
        {e.documents.map((d) => <div className="card" key={d.id}><Link href={`/d/${d.id}`}>{d.title}</Link> {d.issuer && <IssuerTag i={d.issuer} />}</div>)}</>}
      <ReportProblem refId={eventId} kind="grouping" label="Report a problem with this grouping" />
    </>
  );
}
