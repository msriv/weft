import Link from "next/link";
import { RULE_NAMES, STATE_LABEL, ago, perspectiveName } from "@/lib/format";
import type { Anomaly, Issuer, SourceLabel, StoryCard } from "@/lib/types";

export function Kicker({ children, anomaly }: { children: React.ReactNode; anomaly?: boolean }) {
  return <div className={`kicker${anomaly ? " anomaly" : ""}`}>{children}</div>;
}

export function SourceTag({ s }: { s: SourceLabel }) {
  return (
    <span className="row" style={{ gap: 8 }}>
      <Link href={`/sources/${s.id}`}>{s.name}</Link>
      <span className="pill">{STATE_LABEL[s.state_run]}</span>
      {s.paywalled && <span className="pill">Paywalled: headline and lede only</span>}
    </span>
  );
}

/** Rule 7: a document is labelled by its issuer, and by whether the issuer is a party. */
export function IssuerTag({ i }: { i: Issuer }) {
  return (
    <span className="pill on">
      {i.name} · {i.is_party ? "Party to this story" : "Independent of this story"}
    </span>
  );
}

export function AnomalyCard({ a }: { a: Anomaly }) {
  return (
    <div className="card anomaly">
      <Kicker anomaly>
        Anomaly · {RULE_NAMES[a.rule] ?? a.rule}
        {a.status === "provisional" ? " · provisional" : ""}
      </Kicker>
      <p style={{ color: "var(--anomaly-light)", margin: "6px 0" }}>{a.summary}</p>
      <div className="muted" style={{ fontSize: 12 }}>
        Rule {a.rule} version {a.rule_version} · {a.evidence_ids.length} pieces of evidence ·{" "}
        <Link href={`/nodes/${a.id}`}>See the rule and evidence</Link>
      </div>
    </div>
  );
}

export function StoryRow({ s }: { s: StoryCard }) {
  return (
    <Link href={`/s/${s.id}`} className="card" style={{ display: "block" }}>
      <Kicker>
        {s.beat} · {s.status === "quiet" ? "Quiet" : "Developing"} · {s.perspectives.map(perspectiveName).join(", ")}
      </Kicker>
      <h3 style={{ margin: "6px 0" }}>{s.title}</h3>
      <div className="row muted" style={{ fontSize: 13 }}>
        <span>{s.reports} reports</span><span>{s.sources} sources</span><span>{s.perspectives.length} perspectives</span>
        {s.anomalies > 0 && <span className="pill anomaly">{s.anomalies} anomalies</span>}
        {s.provisional_anomalies > 0 && <span className="pill">{s.provisional_anomalies} provisional</span>}
        <span>Last report {ago(s.last_report_at)}</span>
      </div>
    </Link>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="card muted">{children}</div>;
}
