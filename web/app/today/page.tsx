import Link from "next/link";
import { AnomalyCard, Empty, Kicker, StoryRow } from "@/components/bits";
import FollowedBranches from "@/components/FollowedBranches";
import { api } from "@/lib/api";
import Time from "@/components/Time";
import { count, num, perspectiveName } from "@/lib/format";
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
      <Kicker>Overnight batch{t?.day ? <> · <Time iso={t.day} /></> : ""}</Kicker>
      <h1>Today</h1>
      <p>Who reported what, when, and from where. Weft shows coverage; it never says what is true.</p>
      <hr />
      <Kicker>New since {t ? <Time iso={t.since} relative /> : "yesterday"}</Kicker>
      {t?.new_events.length ? byBeat(t.new_events).map(([beat, evs]) => (
        <section key={beat}>
          <h3>{evs[0].title}</h3>
          {evs.map((e) => (
            <Link key={e.id} href={`/s/${e.story_id}/e/${e.id}`} className="card block">
              <div>{e.thread_label && e.follows ? <span className="muted">Thread {e.thread_label} advanced: </span> : null}{e.label ?? "Untitled event"}</div>
              <div className="muted fs13">
                {e.label_source && `Headline from ${e.label_source} · `}{count(e.outlets, "outlet")} · {e.perspectives.map(perspectiveName).join(", ")}
                {e.new_documents > 0 && ` · ${count(e.new_documents, "new document")}`} · first seen <Time iso={e.first_seen} relative />
              </div>
            </Link>
          ))}
        </section>
      )) : <Empty>No new events since then.</Empty>}
      {t?.whats_new && t.whats_new.length > 0 && <><hr /><Kicker>New in the coverage</Kicker></>}
      {t?.whats_new?.map((n, i) => (
        <Link key={i} href={`/s/${n.story_id}/e/${n.event_id}`} className="row flexd">
          <span className="muted">{n.kind === "new_conflict" ? "Reports conflict on" : n.kind === "gained_perspective" ? `Now also reported from ${n.perspectives.map(perspectiveName).join(", ")}` : "New claim"}</span>
          <span>{n.text}</span>
        </Link>
      ))}
      {t && t.new_anomalies.length > 0 && <><hr /><Kicker>New anomalies</Kicker></>}
      {t && t.new_anomalies.map((a) => <AnomalyCard key={a.id} a={a} />)}
      {t?.directions && <p className="muted fs13"><Link href="/directions">{t.directions}</Link> (model speculation, not reporting).</p>}
      {t && t.changes.length > 0 && (
        <p className="muted fs13">Last nightly run: {t.changes.map((c) => `${num(c.count)} ${c.label.toLowerCase()}`).join(" · ")}.</p>
      )}
      <hr />
      <Kicker>Stories with something new</Kicker>
      {t?.breaking.length ? t.breaking.map((s) => <StoryRow key={s.id} s={s} />) : <Empty>No public story has a new event or anomaly.</Empty>}
      <hr />
      <Kicker>No source has published (events of the last 48 hours)</Kicker>
      {t?.blind_spots.length ? t.blind_spots.map((b) => (
        <div className="card" key={b.event_id}>
          <Link href={`/s/${b.story_id}/e/${b.event_id}`}>{b.title}</Link>
          {b.no_source_published.length > 0 && <p className="muted">No source from {b.no_source_published.map(perspectiveName).join(", ")} has published on this event.</p>}
          {b.untracked.length > 0 && <p className="muted">Weft tracks no source from {b.untracked.map(perspectiveName).join(", ")}.</p>}
        </div>
      )) : <Empty>No public stories yet. Stories appear here once collected and published.</Empty>}
      <hr />
      <Kicker>Branches you follow</Kicker>
      <FollowedBranches stories={all ?? []} />
    </>
  );
}
