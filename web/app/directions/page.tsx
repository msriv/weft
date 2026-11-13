import Link from "next/link";
import { Empty, Kicker } from "@/components/bits";
import { DomainCardView, Record } from "@/components/Directions";
import { api } from "@/lib/api";
import type { Directions } from "@/lib/types";
import { notFound } from "next/navigation";

export default async function DirectionsPage({ searchParams }: { searchParams: Promise<{ facet?: string; subject?: string }> }) {
  const { facet, subject } = await searchParams;
  const d = await api<Directions>("/v1/directions");
  if (!d) notFound(); // off unless the detective flag is on (D22)
  const shown = d.domains.filter((x) => (!facet || x.facet === facet) && (!subject || x.subject === subject));
  const c = d.calibration;
  return (
    <>
      <Kicker>Directions · {d.notice}</Kicker>
      <h1>Where things may be heading</h1>
      <p role="note"><strong>{d.disclaimer}</strong></p>
      <div className="row" style={{ margin: "12px 0" }}>
        <Link className={`pill${!facet ? " on" : ""}`} href="/directions">All</Link>
        {d.facets.map((f) => <Link key={f} className={`pill${facet === f ? " on" : ""}`} href={`/directions?facet=${f}`}>{f}</Link>)}
      </div>
      <div className="grid g2">{shown.map((x) => <DomainCardView key={x.id} d={x} />)}</div>
      {!shown.length && <Empty>No active domain{facet ? ` for ${facet}` : ""}.</Empty>}
      <hr />
      <Kicker>Calibration</Kicker>
      <Record t={c} />
      {c.calibration.length > 0 && (
        <table style={{ fontSize: 13 }}>
          <thead><tr><th>Said</th><th>Questions</th><th>Average said</th><th>Happened</th></tr></thead>
          <tbody>{c.calibration.map((b) => (
            <tr key={b.decile[0]}><td>{Math.round(b.decile[0] * 100)}–{Math.round(b.decile[1] * 100)}%</td><td>{b.n}</td><td>{Math.round(b.said * 100)}%</td><td>{Math.round(b.happened * 100)}%</td></tr>
          ))}</tbody>
        </table>
      )}
      {Object.entries(c.by_origin).map(([o, t]) => <div key={o}><Kicker>{o === "template" ? "Template questions (no model)" : "Model questions"}</Kicker><Record t={t} /></div>)}
      {Object.entries(c.by_facet).map(([f, t]) => <div key={f}><Kicker>{f}</Kicker><Record t={t} /></div>)}
    </>
  );
}
