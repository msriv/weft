import Link from "next/link";
import AnomalyFeedback from "@/components/AnomalyFeedback";
import Time from "@/components/Time";
import { FOOTER, chips, sentence } from "@/lib/anomaly";
import { STATE_LABEL, count, perspectiveName, ruleName } from "@/lib/format";
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
  const prov = a.status === "provisional";
  const { shown, more } = chips(a.evidence ?? []);
  return (
    <div className="stack">
      <div className={`card anomaly${prov ? " provisional" : ""}`}>
        <Kicker anomaly>
          Anomaly · {ruleName(a.rule)}
          {prov && <span className="pill ml8">Provisional</span>}
        </Kicker>
        {prov && a.provisional_reason && <p className="muted fs13 my6">{a.provisional_reason} It may change as more reports arrive.</p>}
        <p className="c-anomaly-light my6">{sentence(a)}</p>
        <AnomalyDetail a={a} />
        {shown.length > 0 && (
          <div className="row fs13" aria-label="Evidence">
            {shown.map((e) => (
              <Link key={e.id} className="pill" href={`/nodes/${e.id}`}>
                {e.outlet} · {perspectiveName(e.perspective)}{e.published_at ? <> · <Time iso={e.published_at} /></> : null}
              </Link>
            ))}
            {more > 0 && <span className="muted">and {more} more</span>}
          </div>
        )}
        <div className="muted fs12 my6">
          {FOOTER} Rule: {ruleName(a.rule)}, version {a.rule_version} · {count(a.evidence_ids.length, "piece")} of evidence ·{" "}
          <Link href={`/nodes/${a.id}`}>See the rule and evidence</Link>
        </div>
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
        {s.beat_name ?? s.beat} · {s.status === "quiet" ? "Quiet" : "Developing"} · {s.perspectives.map(perspectiveName).join(", ")}
      </Kicker>
      <h3 className="my6">{s.title}</h3>
      <div className="row muted fs13">
        <span>{count(s.reports, "report")}</span><span>{count(s.sources, "source")}</span><span>{count(s.perspectives.length, "perspective")}</span>
        {s.anomalies > 0 && <span className="pill anomaly">{count(s.anomalies, "anomaly", "anomalies")}</span>}
        {s.provisional_anomalies > 0 && <span className="pill">{s.provisional_anomalies} provisional</span>}
        <span>Last report <Time iso={s.last_report_at} relative /></span>
      </div>
    </Link>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="card muted">{children}</div>;
}
