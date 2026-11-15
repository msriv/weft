import Link from "next/link";
import { notFound } from "next/navigation";
import { AnomalyCard, Empty, Kicker } from "@/components/bits";
import Conflict from "@/components/Conflict";
import DetectivePanel from "@/components/DetectivePanel";
import FollowButton from "@/components/FollowButton";
import LiveFeed from "@/components/LiveFeed";
import OpenQuestions from "@/components/OpenQuestions";
import StoryGraph from "@/components/StoryGraph";
import { api } from "@/lib/api";
import { ago, day, perspectiveName, shortDay } from "@/lib/format";
import { meta } from "@/lib/meta";
import { TABS, beatName, carriedByAll, conflicts, plural, storyHref, tabOf, type StoryQuery } from "@/lib/story";
import type { StoryGraph as SG } from "@/lib/types";

const shift = (iso: string, d: number) => new Date(Date.parse(iso) + d * 86400000).toISOString().slice(0, 10);

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  const p = await params;
  const x = await api<SG>(`/v1/stories/${p.id}`);
  return meta(x?.story.title, "Coverage of this story by perspective.");
}

export default async function StoryPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<StoryQuery> }) {
  const { id } = await params;
  const q = await searchParams;
  const qs = new URLSearchParams(Object.entries({ at: q.at, until: q.until, days: q.days }).filter((e): e is [string, string] => !!e[1]));
  const g = await api<SG>(`/v1/stories/${id}${qs.size ? `?${qs}` : ""}`);
  if (!g) notFound();
  const w = g.window;
  const sv = g.short_version;
  const tab = tabOf(q);
  const href = (change: Partial<StoryQuery>) => storyHref(id, q, change);
  const st = g.story;
  const active = g.anomalies.filter((a) => a.status === "active").length;
  const prov = g.anomalies.filter((a) => a.status === "provisional").length;
  const clashes = conflicts(sv, g.edges, g.nodes);
  const all = carriedByAll(g);
  const anomalyOn = (eventId: string) => g.anomalies.filter((a) => a.event_id === eventId).length;
  const days = [...new Set(g.events.map((e) => day(e.first_seen)))].sort().reverse();
  return (
    <>
      <Kicker>
        {beatName(st.beat)} · {st.status === "quiet" ? "Quiet" : "Developing"}
        {g.as_of ? ` · Replay of ${shortDay(g.as_of)}` : ""}
      </Kicker>
      <h1>{st.title}</h1>
      <p className="figures fs13 m0" aria-label="Story figures">
        <span><b>{st.reports}</b> reports</span>
        <span><b>{st.sources}</b> {st.sources === 1 ? "outlet" : "outlets"}</span>
        <span><b>{st.perspectives.length}</b> {st.perspectives.length === 1 ? "perspective" : "perspectives"}</span>
        <span><b>{st.events}</b> {st.events === 1 ? "event" : "events"}</span>
        {st.last_report_at && <span>last report {ago(st.last_report_at)}</span>}
        <span className={active || prov ? "c-anomaly-light" : ""}>{active} active{prov ? `, ${prov} provisional` : ""} {active + prov === 1 ? "anomaly" : "anomalies"}</span>
      </p>
      <div className="row my12">
        <Link className={`btn small switch`} aria-pressed={!!q.live} href={href({ live: q.live ? "" : "1" })}>{q.live ? "Live: on" : "Go live"}</Link>
        <FollowButton beat={st.beat} />
        <nav className="row muted fs13" aria-label="Story window">
          <span>{w.from ? `${shortDay(w.from)} to ${shortDay(w.to)}` : "Whole story"}</span>
          {w.from && w.older && <Link className="btn small" href={href({ until: shift(w.from, -1) })}>Previous week</Link>}
          {q.until && w.from && <Link className="btn small" href={href({ until: shift(w.to, w.days) })}>Next week</Link>}
          {(q.until || q.days) && <Link className="btn small" href={href({ until: "", days: "" })}>Latest</Link>}
          {w.from && <Link className="btn small" href={href({ days: "0", until: "" })}>Whole story</Link>}
        </nav>
      </div>
      {g.as_of && <p className="c-anomaly-light">You are looking at a replay of {shortDay(g.as_of)}. <Link href={href({ at: "" })}>Back to now</Link></p>}

      <nav className="tabs" aria-label="Story sections">
        {TABS.map(([k, label]) => <Link key={k} href={href({ tab: k })} aria-current={tab === k ? "page" : undefined}>{label}</Link>)}
      </nav>
      {q.live && <LiveFeed storyId={id} />}

      {tab === "overview" && (
        <>
          <section aria-label="Where accounts differ">
            <Kicker anomaly>Where accounts differ</Kicker>
            {clashes.length ? clashes.slice(0, 6).map((c, i) => <Conflict key={i} a={c.a} b={c.b} href={`/s/${id}/e/${c.event_id}`} />)
              : <Empty>No conflicting claims recorded.</Empty>}
            {g.anomalies.length > 0 && <p className="fs13"><Link href={href({ tab: "anomalies" })}>{plural(g.anomalies.length, "anomaly", "anomalies")} flagged by written rules</Link></p>}
          </section>
          <section aria-label="Carried by every perspective" className="mt24">
            <Kicker>Carried by every perspective</Kicker>
            {all.length ? all.slice(0, 8).map((x) => <p key={x.text}>{x.text}{x.coverage && <span className="muted fs13"> · {x.coverage}</span>}</p>)
              : <p className="muted">No claim is carried by every perspective yet.</p>}
          </section>
          <div className="grid g2 mt24">
            <div className="card">
              <Kicker>One perspective only</Kicker>
              {sv.one_perspective_only.length ? sv.one_perspective_only.slice(0, 5).map((x, i) => <p key={i}>{perspectiveName(x.perspective)}: {x.label}</p>) : <p className="muted">None.</p>}
            </div>
            <div className="card">
              <Kicker>No source has published</Kicker>
              {sv.no_source_published.length ? <p>No source from {sv.no_source_published.map(perspectiveName).join(", ")} has published on some events of this story.</p> : null}
              {sv.untracked?.length ? <p className="muted">Weft tracks no source from {sv.untracked.map(perspectiveName).join(", ")}, so their coverage cannot show here.</p> : null}
              {!sv.no_source_published.length && !sv.untracked?.length && <p className="muted">Every party to the story has at least one published report.</p>}
            </div>
          </div>
          <p className="muted fs13"><Link href={href({ tab: "questions" })}>Open questions about this coverage</Link></p>
        </>
      )}

      {tab === "timeline" && (
        <section aria-label="Events, newest first">
          {days.length ? days.map((d) => (
            <div key={d}>
              <h3>{shortDay(d)}</h3>
              {g.events.filter((e) => day(e.first_seen) === d).map((e) => (
                <div className="card" id={`event-${e.id}`} key={e.id}>
                  <h3 className="m0"><Link href={`/s/${id}/e/${e.id}`}>{e.label ?? "Event"}</Link></h3>
                  <div className="row mt8">
                    {e.perspectives.map((p) => <span className="pill" key={p}>{perspectiveName(p)}</span>)}
                    <span className="muted fs13">{plural(e.reports, "report")}</span>
                    {anomalyOn(e.id) > 0 && <span className="pill anomaly">{plural(anomalyOn(e.id), "anomaly", "anomalies")}</span>}
                    {e.thread_label && <span className="muted fs13">Thread: {e.thread_label}</span>}
                    {e.follows && <a className="fs13" href={`#event-${e.follows}`}>follows an earlier event</a>}
                  </div>
                </div>
              ))}
            </div>
          )) : <Empty>No events in this window.</Empty>}
        </section>
      )}

      {tab === "network" && (
        <div className="graph-mode">
          <div className="wide-only">
            <StoryGraph storyId={id} nodes={g.nodes} edges={g.edges} perspectives={g.perspectives} anomalies={g.anomalies} events={g.events} />
          </div>
          {/* phones: one tap to open the graph, scrolling sideways at a readable size */}
          <details className="narrow-only graph-details">
            <summary>Show the network graph</summary>
            <div className="scroll-x"><div className="graph-min">
              <StoryGraph storyId={id} nodes={g.nodes} edges={g.edges} perspectives={g.perspectives} anomalies={g.anomalies} events={g.events} />
            </div></div>
          </details>
          <p className="muted fs13 events-first">Each circle is a group of reports from one perspective on one day. The Timeline tab lists the same events as text.</p>
        </div>
      )}

      {tab === "anomalies" && (
        <section aria-label="Anomalies">
          <Kicker anomaly>Anomalies</Kicker>
          {g.anomalies.length ? g.anomalies.map((a) => <AnomalyCard key={a.id} a={a} />)
            : <Empty>No anomalies. Every flag comes from a written rule you can read on <Link href="/method">How we weigh</Link>.</Empty>}
          <p className="muted fs13">Weight changes the order sources appear in. No report is hidden.</p>
        </section>
      )}

      {tab === "questions" && (
        <div className="stack">
          <OpenQuestions storyId={id} />
          <DetectivePanel storyId={id} />
        </div>
      )}
    </>
  );
}
