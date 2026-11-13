import Link from "next/link";
import { Kicker } from "@/components/bits";
import { day } from "@/lib/format";
import type { DomainCard, Speculation, TrackRecord } from "@/lib/types";

// World directions (D22). Dashed border and a neutral kicker: orange stays for anomalies.
const CARD = { borderStyle: "dashed" } as const;

export function Strip({ d }: { d: DomainCard }) {
  const w = d.direction.coverage_by_week;
  const max = Math.max(1, ...w);
  const pts = d.direction.series?.points ?? [];
  const lo = Math.min(...pts.map((p) => p[1])), hi = Math.max(...pts.map((p) => p[1]));
  return (
    <div className="row" style={{ gap: 16, alignItems: "flex-end", margin: "6px 0" }} aria-label="Computed signals">
      <div title="Independent texts behind the drivers, per week (oldest first)">
        <div style={{ display: "flex", gap: 2, alignItems: "flex-end", height: 24 }}>
          {w.map((n, i) => <span key={i} style={{ width: 8, height: `${(n / max) * 24}px`, background: "var(--muted, #888)" }} />)}
        </div>
        <span className="muted" style={{ fontSize: 11 }}>Coverage, 4 weeks</span>
      </div>
      {pts.length > 1 && (
        <div title={d.direction.series?.source}>
          <svg width={120} height={24} aria-label={`${d.direction.series?.id} reference rate`}>
            <polyline fill="none" stroke="currentColor" strokeWidth={1}
              points={pts.map((p, i) => `${(i / (pts.length - 1)) * 120},${24 - ((p[1] - lo) / (hi - lo || 1)) * 24}`).join(" ")} />
          </svg>
          <div className="muted" style={{ fontSize: 11 }}>{d.direction.series?.id}, last {pts.length} rates</div>
        </div>
      )}
    </div>
  );
}

export function SpeculationRow({ p }: { p: Speculation }) {
  const pct = p.probability === null ? null : Math.round(p.probability * 100);
  return (
    <div style={{ marginTop: 10 }}>
      <p style={{ margin: 0 }}>{p.text}</p>
      {pct !== null && (
        <div aria-label={`${p.origin === "template" ? "Base rate" : "Model's probability"} ${pct}%`} style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div className="bar" style={{ flex: 1 }}><i style={{ width: `${pct}%` }} /></div>
          <span className="kicker">{pct}%</span>
        </div>
      )}
      <p className="muted" style={{ fontSize: 12, margin: 0 }}>
        {p.origin === "template" ? "Template question, no model" : `Model ${p.model ?? ""} · ${p.prompt ?? ""}`} · by {day(p.expected_by)} · {p.outcome}
        {p.base_rate !== null && ` · base rate ${Math.round(p.base_rate * 100)}%`}
      </p>
    </div>
  );
}

export function Record({ t }: { t: TrackRecord }) {
  return (
    <p className="muted" style={{ fontSize: 12 }}>
      {t.resolved} resolved
      {t.brier !== null && ` · Brier ${t.brier.toFixed(2)} (always saying 50% scores ${t.brier_half}`}
      {t.brier !== null && (t.brier_base_rate !== null ? `; the base rate scores ${t.brier_base_rate.toFixed(2)})` : "; no base rate yet)")}
      {t.brier !== null ? ". Lower is better." : "."}
    </p>
  );
}

export function DomainCardView({ d }: { d: DomainCard }) {
  return (
    <div className="card" style={CARD}>
      <Kicker>{d.notice} · {d.facet}</Kicker>
      <h3><Link href={`/directions/${encodeURIComponent(d.id)}`}>{d.label}</Link></h3>
      {d.not_advice && <p className="muted" style={{ fontSize: 12 }}>{d.not_advice}</p>}
      <Strip d={d} />
      {d.open.length ? d.open.map((p) => <SpeculationRow key={p.id} p={p} />) : <p className="muted">No open speculation.</p>}
      {d.drivers.length > 0 && (
        <>
          <Kicker>Drawn from</Kicker>
          {d.drivers.map((g) => (
            <p key={g.group_id} style={{ fontSize: 13, margin: "4px 0" }}>
              <Link href={`/nodes/${g.group_id}`}>{g.label}</Link> <span className="muted">· {g.outlets.slice(0, 4).join(", ")}{g.outlets.length > 4 ? ` and ${g.outlets.length - 4} more` : ""}</span>
            </p>
          ))}
        </>
      )}
      <Record t={d.track_record} />
    </div>
  );
}
