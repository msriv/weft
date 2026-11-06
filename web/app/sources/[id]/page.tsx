import Link from "next/link";
import { notFound } from "next/navigation";
import ReportProblem from "@/components/ReportProblem";
import { AnomalyCard, Kicker } from "@/components/bits";
import { api } from "@/lib/api";
import { STATE_LABEL, perspectiveName } from "@/lib/format";
import type { Anomaly, SourceLabel } from "@/lib/types";

type Profile = {
  source: SourceLabel; factors: Record<string, number | null> | null; factor_names: string[];
  history: { day: string; weight: number }[]; anomalies: Anomaly[]; same_owner: string[];
  index: { reports: number; claims: number; stories: number; tracked_since: string }; weight_note: string;
};

const FACTORS: Record<string, [string, "raises" | "lowers"]> = {
  names_sources: ["Names the source of its claims", "raises"], links_documents: ["Links the official documents it cites", "raises"],
  corrects_openly: ["Corrections issued openly", "raises"], silent_edits: ["Silent edits detected", "lowers"],
  copied_wording: ["Copied wording", "lowers"], opinion_share: ["Share of output that is opinion", "lowers"],
};

export default async function SourcePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const p = await api<Profile>(`/v1/sources/${id}`);
  if (!p) notFound();
  const s = p.source;
  return (
    <>
      <Kicker>Source · {perspectiveName(s.perspective)} · {s.type} · {STATE_LABEL[s.state_run]}</Kicker>
      <h1>{s.name}</h1>
      <div className="row"><div className="stat">{s.weight_insufficient ? "—" : s.weight?.toFixed(2)}</div><div className="kicker">Current weight{s.weight_insufficient ? " · not enough reports yet" : ""}</div></div>
      <p className="muted">{p.weight_note}</p>
      {p.history.length > 1 && (
        <svg viewBox="0 0 300 60" role="img" aria-label="Weight over time" style={{ width: "100%", maxWidth: 480 }}>
          <polyline fill="none" stroke="var(--text)" points={p.history.map((h, i) => `${(i / (p.history.length - 1)) * 300},${58 - h.weight * 56}`).join(" ")} />
        </svg>
      )}
      <hr />
      <Kicker>Why this weight</Kicker>
      {p.factor_names.map((f) => {
        const v = p.factors?.[f];
        return (
          <div key={f} style={{ margin: "8px 0" }}>
            <div className="row"><span>{FACTORS[f][0]}</span><span className="pill">{FACTORS[f][1]}</span><span className="muted">{v == null ? "no data yet" : `${Math.round(v * 100)}%`}</span></div>
            {v != null && <div className="bar"><i style={{ width: `${v * 100}%` }} /></div>}
          </div>
        );
      })}
      <hr />
      <Kicker anomaly>Recent anomalies involving this outlet</Kicker>
      {p.anomalies.length ? p.anomalies.map((a) => <AnomalyCard key={a.id} a={a} />) : <p className="muted">None.</p>}
      <hr />
      <Kicker>Who owns it</Kicker>
      <p>{s.owner_id ? <>{s.owner_id}. <a href={s.ownership_source ?? "#"}>Source of this ownership claim</a>.</> : "Ownership unverified: we have not found a public filing for it."}</p>
      {p.same_owner.length > 0 && <p className="muted">Also owns {p.same_owner.join(", ")} in our index.</p>}
      <Kicker>In our index</Kicker>
      <div className="row"><span>{p.index.reports} reports</span><span>{p.index.claims} claims</span><span>{p.index.stories} stories</span><span className="muted">tracked since {p.index.tracked_since.slice(0, 10)}</span></div>
      <p><a href={s.homepage} rel="noopener noreferrer">Homepage ↗</a> · <Link href="/method">Full methodology</Link></p>
      <ReportProblem refId={id} kind="source" label="Think this is wrong? Report it" />
    </>
  );
}
