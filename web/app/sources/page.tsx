import Link from "next/link";
import { Empty, Kicker } from "@/components/bits";
import { api } from "@/lib/api";
import { STATE_LABEL, perspectiveName } from "@/lib/format";
import type { SourceLabel } from "@/lib/types";

export default async function Sources() {
  const s = (await api<SourceLabel[]>("/v1/sources")) ?? [];
  return (
    <>
      <Kicker>{s.length} sources in our index</Kicker>
      <h1>Sources</h1>
      <p>Sorted by weight, which only changes the order. No report is hidden because of it.</p>
      {s.length ? s.map((x) => (
        <Link href={`/sources/${x.id}`} className="card" style={{ display: "block" }} key={x.id}>
          <div className="row"><h3>{x.name}</h3><span className="pill">{x.type}</span><span className="pill">{perspectiveName(x.perspective)}</span><span className="pill">{STATE_LABEL[x.state_run]}</span></div>
          <div className="muted">{x.weight_insufficient ? "Not enough reports to weigh yet" : `Weight ${x.weight?.toFixed(2)}`}{x.healthy ? "" : " · feed currently unhealthy"}</div>
        </Link>
      )) : <Empty>Discovery has not registered any sources yet.</Empty>}
    </>
  );
}
