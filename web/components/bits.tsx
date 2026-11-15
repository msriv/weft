import Link from "next/link";
import AnomalyFeedback from "@/components/AnomalyFeedback";
import { RULE_NAMES, STATE_LABEL, ago, perspectiveName } from "@/lib/format";
import type { Anomaly, Issuer, SourceLabel, StoryCard } from "@/lib/types";

export function Kicker({ children, anomaly }: { children: React.ReactNode; anomaly?: boolean }) {
  return <div className={`kicker${anomaly ? " anomaly" : ""}`}>{children}</div>;
}

export function SourceTag({ s }: { s: SourceLabel }) {
  return (
    <span className="row gap8">
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
      <p className="c-anomaly-light my6">{a.summary}</p>
      <AnomalyDetail a={a} />
      <div className="muted fs12">
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
  if (a.rule === "quote_differs" && str(d.quote)) {
    return (
      <div className="row gap12 is my6">
        <blockquote className="flex1 m0">Quoted: {str(d.quote)}</blockquote>
        <blockquote className="flex1 m0">Issued by {str(d.issuer)}: {str(d.statement)}</blockquote>
      </div>
    );
  }
  if (a.rule === "conflicting_accounts" && Array.isArray(d.sides)) {
    const sides = d.sides as { label: string; perspectives: string[] }[];
    return (
      <div className="row gap12 is my6">
        {sides.map((x, i) => (
          <blockquote key={i} className="flex1 m0">{x.label}<div className="muted fs12">Carried by {x.perspectives.map(perspectiveName).join(", ")}</div></blockquote>
        ))}
      </div>
    );
  }
  if (["omission", "unattributed", "anonymous_sourcing", "single_origin"].includes(a.rule) && str(d.label)) {
    return <blockquote className="my6">Claim group: {str(d.label)}</blockquote>;
  }
  if ((a.rule === "numbers_differ" || a.rule === "figure_revised") && Array.isArray(d.figures)) {
    const figs = d.figures as { id: string; text: string; value: number }[];
    return (
      <div className="row gap12 is my6">
        {figs.map((f) => (
          <blockquote key={f.id} className="flex1 m0"><b>{f.value}</b> · {f.text}</blockquote>
        ))}
      </div>
    );
  }
  if (a.rule === "silent_edit" && Array.isArray(d.diff)) {
    const lines = (d.diff as string[]).slice(0, max);
    return (
      <pre className="prewrap fs12 my6">
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
    return <p className="muted my6">Word: “{str(d.term)}”</p>;
  }
  return null;
}

export function StoryRow({ s }: { s: StoryCard }) {
  return (
    <Link href={`/s/${s.id}`} className="card block">
      <Kicker>
        {s.beat} · {s.status === "quiet" ? "Quiet" : "Developing"} · {s.perspectives.map(perspectiveName).join(", ")}
      </Kicker>
      <h3 className="my6">{s.title}</h3>
      <div className="row muted fs13">
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
