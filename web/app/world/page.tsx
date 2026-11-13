import Link from "next/link";
import Globe from "@/components/Globe";
import { Empty, Kicker } from "@/components/bits";
import { api } from "@/lib/api";
import { perspectiveName } from "@/lib/format";
import type { Directions, World } from "@/lib/types";

export default async function WorldPage({ searchParams }: { searchParams: Promise<{ view?: string }> }) {
  const { view } = await searchParams;
  const w = (await api<World>("/v1/world")) ?? { stories: [], gaps: [] };
  const byStory = Map.groupBy(w.stories, (s) => s.story_id);
  // countries with a directions domain; empty unless the detective flag is on (D22)
  const dir = await api<Directions>("/v1/directions").catch(() => null);
  const withDirections = [...new Set((dir?.domains ?? []).filter((d) => d.subject_kind === "country").map((d) => d.subject))];
  return (
    <>
      <Kicker>World desk</Kicker>
      <h1>Where the reporting comes from</h1>
      <div className="row" style={{ margin: "12px 0" }}>
        <Link className={`pill${view !== "globe" ? " on" : ""}`} href="/world">Threads</Link>
        <Link className="pill" href="/">Globe</Link>
      </div>
      {view === "globe" ? <Globe world={w} directions={withDirections} /> : (
        <>
          {[...byStory.entries()].map(([id, items]) => (
            <div className="card" key={id}>
              <h3><Link href={`/s/${id}`}>{items[0].title}</Link></h3>
              <div className="row" style={{ marginTop: 8 }}>
                {items.map((i) => <span key={i.country} className="pill on">{perspectiveName(i.country)} · {i.reports}</span>)}
              </div>
              {items.some((i) => withDirections.includes(i.country)) && (
                <p className="muted" style={{ fontSize: 13 }}>
                  {items.filter((i) => withDirections.includes(i.country)).map((i) => <Link key={i.country} href={`/directions?subject=${i.country}`} style={{ marginRight: 8 }}>Directions for {perspectiveName(i.country)}</Link>)}
                </p>
              )}
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
