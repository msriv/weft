import Link from "next/link";
import Globe from "@/components/Globe";
import { Empty, Kicker } from "@/components/bits";
import { api } from "@/lib/api";
import { perspectiveName } from "@/lib/format";
import type { World } from "@/lib/types";

export default async function WorldPage({ searchParams }: { searchParams: Promise<{ view?: string }> }) {
  const { view } = await searchParams;
  const w = (await api<World>("/v1/world")) ?? { stories: [], gaps: [] };
  const byStory = Map.groupBy(w.stories, (s) => s.story_id);
  return (
    <>
      <Kicker>World desk</Kicker>
      <h1>Where the reporting comes from</h1>
      <div className="row" style={{ margin: "12px 0" }}>
        <Link className={`pill${view !== "globe" ? " on" : ""}`} href="/world">Threads</Link>
        <Link className="pill" href="/">Globe</Link>
      </div>
      {view === "globe" ? <Globe world={w} /> : (
        <>
          {[...byStory.entries()].map(([id, items]) => (
            <div className="card" key={id}>
              <h3><Link href={`/s/${id}`}>{items[0].title}</Link></h3>
              <div className="row" style={{ marginTop: 8 }}>
                {items.map((i) => <span key={i.country} className="pill on">{perspectiveName(i.country)} · {i.reports}</span>)}
              </div>
            </div>
          ))}
          {!byStory.size && <Empty>No public stories yet.</Empty>}
          <hr />
          <Kicker>Coverage gaps</Kicker>
          <p className="muted">Places where we hold few reports on a story they are party to. This describes our coverage, not the story.</p>
          {w.gaps.map((g) => <div className="card" key={`${g.story_id}-${g.country}`}>{perspectiveName(g.country)} · {g.reports} reports · <Link href={`/s/${g.story_id}`}>{g.title}</Link></div>)}
        </>
      )}
    </>
  );
}
