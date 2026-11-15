/** Result of an action. Announced to screen readers; errors interrupt, the rest wait their turn. */
export default function Status({ kind, children }: { kind: "ok" | "error" | "busy"; children?: React.ReactNode }) {
  if (!children) return <span role="status" aria-live="polite" />;
  return kind === "error"
    ? <span role="alert" className="c-anomaly-light fs13">{children}</span>
    : <span role="status" aria-live="polite" className="muted fs13">{children}</span>;
}
