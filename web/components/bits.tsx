import Link from "next/link";
import AnomalyFeedback from "@/components/AnomalyFeedback";
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
      {i.name} · {i.is_party ? "Party to this story" : "Not listed as a party to this story"}
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
      <AnomalyDetail a={a} />
      <div className="muted" style={{ fontSize: 12 }}>
        Rule {a.rule} version {a.rule_version} · {a.evidence_ids.length} pieces of evidence ·{" "}
        <Link href={`/nodes/${a.id}`}>See the rule and evidence</Link>
      </div>
      <AnomalyFeedback id={a.id} />
    </div>
  );
}

const str = (v: unknown) => (typeof v === "string" ? v : "");

/** What the rule looked at, shown per rule: the claim, the two figures, or the changed lines. */
export function AnomalyDetail({ a, max = 6 }: { a: Pick<Anomaly, "rule" | "detail">; max?: number }) {
  const d = a.detail ?? {};
  if ((a.rule === "omission" || a.rule === "unattributed") && str(d.label)) {
    return <blockquote style={{ margin: "6px 0" }}>Claim group: {str(d.label)}</blockquote>;
  }
  if (a.rule === "numbers_differ" && Array.isArray(d.figures)) {
    const figs = d.figures as { id: string; text: string; value: number }[];
    return (
      <div className="row" style={{ gap: 12, alignItems: "stretch", margin: "6px 0" }}>
        {figs.map((f) => (
          <blockquote key={f.id} style={{ flex: 1, margin: 0 }}><b>{f.value}</b> · {f.text}</blockquote>
        ))}
      </div>
    );
  }
  if (a.rule === "silent_edit" && Array.isArray(d.diff)) {
    const lines = (d.diff as string[]).slice(0, max);
    return (
      <pre style={{ whiteSpace: "pre-wrap", fontSize: 12, margin: "6px 0" }}>
        {lines.map((ln, i) => (
          <div key={i} style={{ color: ln.startsWith("-") ? "var(--anomaly-light)" : undefined }}>
            {ln.startsWith("-") ? "Removed: " : "Added: "}{ln.slice(1)}
          </div>
        ))}
        {(d.diff as string[]).length > max && <div className="muted">and more changed lines</div>}
      </pre>
    );
  }
  if (a.rule === "loaded_wording" && str(d.term)) {
    return <p className="muted" style={{ margin: "6px 0" }}>Word: “{str(d.term)}”</p>;
  }
  return null;
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
