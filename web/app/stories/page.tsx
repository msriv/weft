import Link from "next/link";
import { Empty, Kicker, StoryRow } from "@/components/bits";
import { api } from "@/lib/api";
import { perspectiveName } from "@/lib/format";
import type { StoryCard } from "@/lib/types";

type Q = { region?: string; topic?: string; sort?: string };

export default async function Stories({ searchParams }: { searchParams: Promise<Q> }) {
  const q = await searchParams;
  const qs = new URLSearchParams(Object.entries(q).filter(([, v]) => v) as [string, string][]);
  const [shown, all] = await Promise.all([
    api<StoryCard[]>(`/v1/stories?${qs}`), api<StoryCard[]>("/v1/stories"),
  ]);
  const regions = [...new Set((all ?? []).flatMap((s) => s.perspectives))].sort();
  const topics = [...new Map((all ?? []).map((s) => [s.beat, s.title])).entries()];
  const link = (patch: Partial<Q>) => {
    const n = new URLSearchParams({ ...q, ...patch } as Record<string, string>);
    for (const [k, v] of [...n]) if (!v) n.delete(k);
    return `/stories?${n}`;
  };
  return (
    <>
      <Kicker>{all?.length ?? 0} stories tracked</Kicker>
      <h1>All stories</h1>
      <div className="row" style={{ margin: "16px 0" }}>
        <span className="kicker">Sort</span>
        {[["recent", "Recent"], ["anomalies", "Most anomalies"], ["reports", "Most reports"]].map(([k, l]) => (
          <Link key={k} className={`pill${(q.sort ?? "recent") === k ? " on" : ""}`} href={link({ sort: k })}>{l}</Link>
        ))}
      </div>
      <div className="row">
        <span className="kicker">Region</span>
        <Link className={`pill${!q.region ? " on" : ""}`} href={link({ region: "" })}>Everywhere</Link>
        {regions.map((r) => <Link key={r} className={`pill${q.region === r ? " on" : ""}`} href={link({ region: r })}>{perspectiveName(r)}</Link>)}
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <span className="kicker">Topic</span>
        <Link className={`pill${!q.topic ? " on" : ""}`} href={link({ topic: "" })}>All</Link>
        {topics.map(([beat, title]) => <Link key={beat} className={`pill${q.topic === beat ? " on" : ""}`} href={link({ topic: beat })}>{title}</Link>)}
      </div>
      <div style={{ marginTop: 16 }}>
        {shown?.length ? shown.map((s) => <StoryRow key={s.id} s={s} />) : <Empty>No public stories match.</Empty>}
      </div>
    </>
  );
}
