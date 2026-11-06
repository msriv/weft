import { Kicker } from "@/components/bits";
import ReportProblem from "@/components/ReportProblem";
import { api } from "@/lib/api";
import { RULE_NAMES } from "@/lib/format";

type Method = {
  rules_version: number; provisional: Record<string, number>; rules: Record<string, Record<string, unknown>>;
  weights: { factors: { id: string; name: string; how: string; direction: string }[] };
  models: { job: string; model: string; how: string }[]; model_calls_note: string;
  corrections: { day: string; kind: string; what: string }[]; gdelt_citation: string;
};

export default async function MethodPage() {
  const m = await api<Method>("/v1/method");
  if (!m) return <p>Unavailable.</p>;
  return (
    <>
      <Kicker>How we weigh · rules version {m.rules_version}</Kicker>
      <h1>We don&apos;t decide what&apos;s true.</h1>
      <p>Weft shows who reported what, when, and from where. We flag places where reports don&apos;t line up. Every flag comes from a written rule you can read below.</p>
      <hr />
      <Kicker>What we collect</Kicker>
      <p>News outlets from every country involved, with state-run outlets labelled where a citation exists. Official documents, labelled by issuer and by whether the issuer is a party to the story. Blogs and analysts, weighted lower and marked as opinion. We store summaries and links, not full articles.</p>
      <hr />
      <Kicker>How a source&apos;s weight is set</Kicker>
      <p>Weight only changes the order things appear in. No report is ever hidden. We never score a source on whether it was right, only on how it reports.</p>
      {m.weights.factors.map((f) => (
        <div className="row" key={f.id}><b>{f.name}</b><span className="pill">{f.direction}</span><span className="muted">{f.how}</span></div>
      ))}
      <hr />
      <Kicker>The anomaly rules</Kicker>
      <p>Anomalies compare reports with other reports, never with &ldquo;the truth&rdquo;. No AI model flags anomalies. Anomalies stay provisional until at least {m.provisional.min_sources} sources from {m.provisional.min_perspectives} perspectives have reported and {m.provisional.min_hours_since_first_report} hours have passed.</p>
      {Object.entries(m.rules).map(([k, v]) => (
        <div className="card" key={k}>
          <Kicker>{RULE_NAMES[k] ?? k}{v.enabled ? "" : " · not yet active"}</Kicker>
          <pre style={{ margin: 0, fontSize: 12, color: "var(--body2)" }}>{Object.entries(v).filter(([n]) => n !== "enabled").map(([n, x]) => `${n}: ${JSON.stringify(x)}`).join("\n")}</pre>
        </div>
      ))}
      <hr />
      <Kicker>Where we use AI models</Kicker>
      <p>{m.model_calls_note} Never used for: flagging anomalies, scoring sources, or deciding what a story is about.</p>
      {m.models.map((x) => <div className="row" key={x.job}><b>{x.job}</b><span className="muted">{x.model}</span><span>{x.how}</span></div>)}
      <hr />
      <Kicker>Who pays for Weft</Kicker>
      <p>Reader subscriptions and donations, when they start. No advertising, because ads reward exactly the engagement we&apos;re trying not to create. No funding from governments or parties covered in our stories.</p>
      <p className="muted">{m.gdelt_citation}</p>
      <hr />
      <Kicker>Our own mistakes</Kicker>
      <p>Every correction Weft makes to its own groupings, translations or flags.</p>
      {m.corrections.length ? m.corrections.map((c, i) => <div className="row" key={i}><span className="kicker">{c.day}</span><span className="pill">{c.kind}</span><span>{c.what}</span></div>) : <p className="muted">No corrections yet.</p>}
      <ReportProblem kind="other" label="Report a problem" />
    </>
  );
}
