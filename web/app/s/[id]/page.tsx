import Link from "next/link";
import { notFound } from "next/navigation";
import { AnomalyCard, Empty, Kicker } from "@/components/bits";
import DetectivePanel from "@/components/DetectivePanel";
import FollowButton from "@/components/FollowButton";
import LiveFeed from "@/components/LiveFeed";
import OpenQuestions from "@/components/OpenQuestions";
import StoryGraph from "@/components/StoryGraph";
import { api } from "@/lib/api";
import { meta } from "@/lib/meta";
import { day, perspectiveName } from "@/lib/format";
import type { StoryGraph as SG } from "@/lib/types";

type Q = { view?: string; at?: string; live?: string; until?: string; days?: string };

const shift = (iso: string, d: number) => new Date(Date.parse(iso) + d * 86400000).toISOString().slice(0, 10);

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  const p = await params;
  const x = await api<SG>(`/v1/stories/${p.id}`);
  return meta(x?.story.title, "Coverage of this story by perspective.");
}

export default async function StoryPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<Q> }) {
  const { id } = await params;
  const q = await searchParams;
  const qs = new URLSearchParams(Object.entries({ at: q.at, until: q.until, days: q.days }).filter((e): e is [string, string] => !!e[1]));
  const g = await api<SG>(`/v1/stories/${id}${qs.size ? `?${qs}` : ""}`);
  if (!g) notFound();
  const w = g.window;
  const page = (p: Record<string, string>) => `/s/${id}?${new URLSearchParams({ ...(q.at ? { at: q.at } : {}), ...(q.view ? { view: q.view } : {}), ...p })}`;
  const sv = g.short_version;
  const list = q.view === "list";
  return (
    <>
      <Kicker>
        {g.story.beat} · {g.story.status === "quiet" ? "Quiet" : "Developing"}
        {g.as_of ? ` · Replay of ${day(g.as_of)}` : ""}
      </Kicker>
      <h1>{g.story.title}</h1>
      <div className="row my12">
        <Link className={`pill${!list ? " on" : ""}`} href={`/s/${id}`}>Network</Link>
        <Link className={`pill${list ? " on" : ""}`} href={`/s/${id}?view=list`}>List</Link>
        <Link className={`pill${q.live ? " on" : ""}`} href={`/s/${id}?live=1`}>Go live</Link>
        <FollowButton beat={g.story.beat} />
      </div>
      <nav className="row muted fs13 mb12" aria-label="Story window">
        <span>{w.from ? `Showing ${day(w.from)} to ${day(w.to)}` : "Showing the whole story"}</span>
        {w.from && w.older && <Link href={page({ until: shift(w.from, -1) })}>Older week</Link>}
        {q.until && w.from && <Link href={page({ until: shift(w.to, w.days) })}>Newer week</Link>}
        {(q.until || q.days) && <Link href={page({})}>Latest week</Link>}
        {w.from && <Link href={page({ days: "0" })}>Whole story</Link>}
      </nav>

      <div className="story-layout">
      <div>
      <div className="grid g2">
        <div className="card">
          <Kicker>Reported by all perspectives</Kicker>
          {sv.reported_by_all.length ? sv.reported_by_all.slice(0, 6).map((x) => <p key={x.label}>{x.label}</p>) : <p className="muted">No claim is carried by every perspective yet.</p>}
        </div>
        <div className="card">
          {g.summary_items?.length ? (
            <>
              <Kicker>Most carried claims of the last 48 hours</Kicker>
              {g.summary_items.map((x, i) => <p key={i} className="fs13">{x.text} <span className="muted">· {x.coverage}</span></p>)}
              <p className="muted fs12">Ranked by how many independent texts and perspectives carry each claim.</p>
            </>
          ) : (
            <>
              <Kicker>Opening lines from the latest week's reports</Kicker>
              {g.summary.length ? g.summary.map((x, i) => <p key={i} className="muted fs13">{x}</p>) : <p className="muted">None yet.</p>}
              <p className="muted fs12">Taken from single outlets. Not carried by every perspective.</p>
            </>
          )}
        </div>
        <div className="card">
          <Kicker anomaly>Reports conflict on</Kicker>
          {sv.reports_conflict_on.length ? sv.reports_conflict_on.slice(0, 6).map((x, i) => <p key={i}>{x.labels.join(" — versus — ")}</p>) : <p className="muted">No conflicting claims recorded.</p>}
        </div>
        <div className="card">
          <Kicker>No source has published</Kicker>
          {sv.no_source_published.length ? <p>No source from {sv.no_source_published.map(perspectiveName).join(", ")} has published on some events of this story.</p> : null}
          {sv.untracked?.length ? <p className="muted">Weft tracks no source from {sv.untracked.map(perspectiveName).join(", ")}, so their coverage cannot show here.</p> : null}
          {!sv.no_source_published.length && !sv.untracked?.length && <p className="muted">Every party to the story has at least one published report.</p>}
        </div>
        <div className="card">
          <Kicker>One perspective only</Kicker>
          {sv.one_perspective_only.length ? sv.one_perspective_only.slice(0, 5).map((x, i) => <p key={i}>{perspectiveName(x.perspective)}: {x.label}</p>) : <p className="muted">None.</p>}
        </div>
      </div>

      {q.live && <LiveFeed storyId={id} />}
      <hr />
      {list ? (
        <section aria-label="Events">
          {g.events.map((e) => (
            <div className="card" id={`event-${e.id}`} key={e.id}>
              <Kicker>{day(e.first_seen)} · {e.perspectives.map(perspectiveName).join(", ")}{e.thread_label ? ` · Thread: ${e.thread_label}` : ""}</Kicker>
              <h3><Link href={`/s/${id}/e/${e.id}`}>{e.label ?? "Event"}</Link></h3>
              {e.label_source && <p className="muted fs12">Headline from {e.label_source}</p>}
              <p className="muted">{e.reports} reports{e.follows && <> · follows <a href={`#event-${e.follows}`}>an earlier event</a></>}</p>
            </div>
          ))}
        </section>
      ) : (
        <div className="graph-mode">
          <div className="wide-only">
            <StoryGraph storyId={id} nodes={g.nodes} edges={g.edges} perspectives={g.perspectives} anomalies={g.anomalies} />
          </div>
          {/* phones: the event list comes first; the graph is one tap away and scrolls sideways at a readable size */}
          <details className="narrow-only graph-details">
            <summary>Show the network graph</summary>
            <div className="scroll-x"><div className="graph-min">
              <StoryGraph storyId={id} nodes={g.nodes} edges={g.edges} perspectives={g.perspectives} anomalies={g.anomalies} />
            </div></div>
          </details>
          <section aria-label="Events" className="mt24 events-first">
            <Kicker>Events</Kicker>
            {g.events.map((e) => (
              <div className="row" id={`event-${e.id}`} key={e.id}>
                <Link href={`/s/${id}/e/${e.id}`}>{e.label ?? "Event"}</Link><span className="muted">{e.thread_label ? `${e.thread_label} · ` : ""}{e.reports} reports</span>
              </div>
            ))}
          </section>
        </div>
      )}
      <hr />
      <Kicker anomaly>Anomalies</Kicker>
      {g.anomalies.length ? g.anomalies.map((a) => <AnomalyCard key={a.id} a={a} />) : <Empty>No anomalies. Every flag comes from a written rule you can read on <Link href="/method">How we weigh</Link>.</Empty>}
      <p className="muted fs13">Weight changes the order sources appear in. No report is hidden.</p>
      </div>
      <div className="stack">
        <OpenQuestions storyId={id} />
        <DetectivePanel storyId={id} />
      </div>
      </div>
    </>
  );
}
