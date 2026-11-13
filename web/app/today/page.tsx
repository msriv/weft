import Link from "next/link";
import { AnomalyCard, Empty, Kicker, StoryRow } from "@/components/bits";
import FollowedBranches from "@/components/FollowedBranches";
import { api } from "@/lib/api";
import { ago, perspectiveName } from "@/lib/format";
import type { NewEvent, StoryCard, Today } from "@/lib/types";

function byBeat(events: NewEvent[]): [string, NewEvent[]][] {
  const m = new Map<string, NewEvent[]>();
  for (const e of events) m.set(e.beat, [...(m.get(e.beat) ?? []), e]);
  return [...m.entries()];
}

export default async function TodayPage() {
  const [t, all] = await Promise.all([api<Today>("/v1/today"), api<StoryCard[]>("/v1/stories")]);
  return (
    <>
      <Kicker>Overnight batch{t?.day ? ` · ${t.day}` : ""}</Kicker>
      <h1>Today</h1>
      <p>Who reported what, when, and from where. Weft shows coverage; it never says what is true.</p>
      <hr />
      <Kicker>New since {t ? ago(t.since) : "yesterday"}</Kicker>
      {t?.new_events.length ? byBeat(t.new_events).map(([beat, evs]) => (
        <section key={beat}>
          <h3>{evs[0].title}</h3>
          {evs.map((e) => (
            <Link key={e.id} href={`/s/${e.story_id}/e/${e.id}`} className="card" style={{ display: "block" }}>
              <div>{e.thread_label && e.follows ? <span className="muted">Thread {e.thread_label} advanced: </span> : null}{e.label ?? "Untitled event"}</div>
              <div className="muted" style={{ fontSize: 13 }}>
                {e.label_source && `Headline from ${e.label_source} · `}{e.outlets} outlets · {e.perspectives.map(perspectiveName).join(", ")}
                {e.new_documents > 0 && ` · ${e.new_documents} new documents`} · first seen {ago(e.first_seen)}
              </div>
            </Link>
          ))}
        </section>
      )) : <Empty>No new events since then.</Empty>}
      {t && t.new_anomalies.length > 0 && <><hr /><Kicker>New anomalies</Kicker></>}
      {t && t.new_anomalies.map((a) => <AnomalyCard key={a.id} a={a} />)}
      {t && t.changes.length > 0 && (
        <p className="muted" style={{ fontSize: 13 }}>Last nightly run: {t.changes.map((c) => `${c.count} ${c.label.toLowerCase()}`).join(" · ")}.</p>
      )}
      <hr />
      <Kicker>Stories with something new</Kicker>
      {t?.breaking.length ? t.breaking.map((s) => <StoryRow key={s.id} s={s} />) : <Empty>No public story has a new event or anomaly.</Empty>}
      <hr />
      <Kicker>No source has published (events of the last 48 hours)</Kicker>
      {t?.blind_spots.length ? t.blind_spots.map((b) => (
        <div className="card" key={b.event_id}>
          <Link href={`/s/${b.story_id}/e/${b.event_id}`}>{b.title}</Link>
          {b.no_source_published.length > 0 && <p className="muted">No source from {b.no_source_published.join(", ")} has published on this event.</p>}
          {b.untracked.length > 0 && <p className="muted">Weft tracks no source from {b.untracked.join(", ")}.</p>}
        </div>
      )) : <Empty>Nothing to show.</Empty>}
      <hr />
      <Kicker>Branches you follow</Kicker>
      <FollowedBranches stories={all ?? []} />
    </>
  );
}
