import { ruleRows } from "@/lib/format";

const label = (k: string) => k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

/** Any stored object as labelled rows. Long text is quoted, lists are lists, nothing is JSON. */
export function Fields({ data }: { data: unknown }) {
  if (data === null || data === undefined || data === "") return <span className="muted">None</span>;
  if (typeof data === "boolean") return <>{data ? "Yes" : "No"}</>;
  if (typeof data === "number") return <>{data.toLocaleString("en-GB")}</>;
  if (typeof data === "string") return data.length > 60 ? <blockquote className="m0">{data}</blockquote> : <>{data}</>;
  if (Array.isArray(data)) {
    return data.length ? <ul className="m0">{data.map((x, i) => <li key={i}><Fields data={x} /></li>)}</ul> : <span className="muted">None</span>;
  }
  const rows = Object.entries(data as Record<string, unknown>);
  return (
    <dl className="fields m0">
      {rows.map(([k, v]) => <div key={k}><dt>{label(k)}</dt><dd><Fields data={v} /></dd></div>)}
    </dl>
  );
}

/** A rule's thresholds as labelled rows. */
export function RuleTable({ rule, values }: { rule: string; values: Record<string, unknown> }) {
  const rows = ruleRows(rule, values);
  if (!rows.length) return <p className="muted m0">No thresholds.</p>;
  return (
    <table className="fs13">
      <tbody>{rows.map(([k, v]) => <tr key={k}><th scope="row">{k}</th><td>{v}</td></tr>)}</tbody>
    </table>
  );
}
