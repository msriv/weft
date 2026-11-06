import Link from "next/link";
import { AnomalyCard, Empty, Kicker, StoryRow } from "@/components/bits";
import FollowedBranches from "@/components/FollowedBranches";
import { api } from "@/lib/api";
import type { StoryCard, Today } from "@/lib/types";

export default async function TodayPage() {
  const [t, all] = await Promise.all([api<Today>("/v1/today"), api<StoryCard[]>("/v1/stories")]);
  return (
    <>
      <Kicker>Overnight batch{t?.day ? ` · ${t.day}` : ""}</Kicker>
      <h1>Today</h1>
      <p>Who reported what, when, and from where. Weft shows coverage; it never says what is true.</p>
      <hr />
      <Kicker>What changed overnight</Kicker>
      {t && t.changes.length > 0 ? (
        <div className="row">{t.changes.map((c) => (
          <div key={c.kind}><div className="stat">{c.count}</div><div className="kicker">{c.label}</div></div>
        ))}</div>
      ) : <Empty>No changes recorded yet. The first nightly run has not finished.</Empty>}
      {t && t.new_anomalies.map((a) => <AnomalyCard key={a.id} a={a} />)}
      <hr />
      <Kicker>Breaking now</Kicker>
      {t?.breaking.length ? t.breaking.map((s) => <StoryRow key={s.id} s={s} />) : <Empty>No developing stories are public yet.</Empty>}
      <hr />
      <Kicker>No source has published</Kicker>
      {t?.blind_spots.length ? t.blind_spots.map((b) => (
        <div className="card" key={b.event_id}>
          <Link href={`/s/${b.story_id}/e/${b.event_id}`}>{b.title}</Link>
          <p className="muted">No source from {b.no_source_published.join(", ")} has published on this event.</p>
        </div>
      )) : <Empty>Nothing to show.</Empty>}
      <hr />
      <Kicker>Branches you follow</Kicker>
      <FollowedBranches stories={all ?? []} />
    </>
  );
}
