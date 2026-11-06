import Link from "next/link";
import { notFound } from "next/navigation";
import { AnomalyCard, Empty, Kicker } from "@/components/bits";
import FollowButton from "@/components/FollowButton";
import LiveFeed from "@/components/LiveFeed";
import StoryGraph from "@/components/StoryGraph";
import { api } from "@/lib/api";
import { day, perspectiveName } from "@/lib/format";
import type { StoryGraph as SG } from "@/lib/types";

type Q = { view?: string; at?: string; live?: string };

export default async function StoryPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<Q> }) {
  const { id } = await params;
  const q = await searchParams;
  const g = await api<SG>(`/v1/stories/${id}${q.at ? `?at=${q.at}` : ""}`);
  if (!g) notFound();
  const sv = g.short_version;
  const list = q.view === "list";
  return (
    <>
      <Kicker>
        {g.story.beat} · {g.story.status === "quiet" ? "Quiet" : "Developing"}
        {g.as_of ? ` · Replay of ${day(g.as_of)}` : ""}
      </Kicker>
      <h1>{g.story.title}</h1>
      <div className="row" style={{ margin: "12px 0" }}>
        <Link className={`pill${!list ? " on" : ""}`} href={`/s/${id}`}>Network</Link>
        <Link className={`pill${list ? " on" : ""}`} href={`/s/${id}?view=list`}>List</Link>
        <Link className={`pill${q.live ? " on" : ""}`} href={`/s/${id}?live=1`}>Go live</Link>
        <FollowButton beat={g.story.beat} />
      </div>

      <div className="grid g2">
        <div className="card">
          <Kicker>Reported by all perspectives</Kicker>
          {sv.reported_by_all.length ? sv.reported_by_all.slice(0, 6).map((x) => <p key={x.label}>{x.label}</p>) : <p className="muted">No claim is carried by every perspective yet.</p>}
          <p className="muted" style={{ fontSize: 13 }}>{g.summary.join(" ")}</p>
        </div>
        <div className="card">
          <Kicker anomaly>Reports conflict on</Kicker>
          {sv.reports_conflict_on.length ? sv.reports_conflict_on.slice(0, 6).map((x, i) => <p key={i}>{x.labels.join(" — versus — ")}</p>) : <p className="muted">No conflicting claims recorded.</p>}
        </div>
        <div className="card">
          <Kicker>No source has published</Kicker>
          {sv.no_source_published.length ? <p>No source from {sv.no_source_published.map(perspectiveName).join(", ")} has published on some events of this story.</p> : <p className="muted">Every party to the story has at least one published report.</p>}
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
              <Kicker>{day(e.first_seen)} · {e.perspectives.map(perspectiveName).join(", ")}</Kicker>
              <h3><Link href={`/s/${id}/e/${e.id}`}>{e.label ?? "Event"}</Link></h3>
              <p className="muted">{e.reports} reports</p>
            </div>
          ))}
        </section>
      ) : (
        <>
          <StoryGraph storyId={id} nodes={g.nodes} edges={g.edges} perspectives={g.perspectives} anomalies={g.anomalies} />
          <section aria-label="Events" style={{ marginTop: 24 }}>
            <Kicker>Events</Kicker>
            {g.events.map((e) => (
              <div className="row" id={`event-${e.id}`} key={e.id}>
                <Link href={`/s/${id}/e/${e.id}`}>{e.label ?? "Event"}</Link><span className="muted">{e.reports} reports</span>
              </div>
            ))}
          </section>
        </>
      )}
      <hr />
      <Kicker anomaly>Anomalies</Kicker>
      {g.anomalies.length ? g.anomalies.map((a) => <AnomalyCard key={a.id} a={a} />) : <Empty>No anomalies. Every flag comes from a written rule you can read on <Link href="/method">How we weigh</Link>.</Empty>}
      <p className="muted" style={{ fontSize: 13 }}>Weight changes the order sources appear in. No report is hidden.</p>
    </>
  );
}
