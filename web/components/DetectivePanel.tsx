import Link from "next/link";
import { Kicker } from "@/components/bits";
import { api } from "@/lib/api";
import { day } from "@/lib/format";

type Prediction = {
  id: string; text: string; probability: number | null; expected_by: string; confirm_if: string; refute_if: string;
  made_at: string; status: "open" | "supported" | "contradicted" | "expired"; evidence: string[];
};
type Card = {
  disclaimer: string; predictions: Prediction[]; counts: Record<Prediction["status"], number>;
  resolved: number; brier: number | null; brier_coin: number;
  calibration: { band: [number, number]; n: number; happened: number }[];
  domains?: { id: string; label: string }[];
};

const STATUS: Record<Prediction["status"], string> = {
  open: "Open", supported: "Later reports say it happened", contradicted: "Later reports say it did not", expired: "Expired, nothing reported (counts as a miss)",
};

// Detective mode (D20): experimental speculation, off unless the API runs with DETECTIVE=on.
export default async function DetectivePanel({ storyId }: { storyId: string }) {
  const c = await api<Card>(`/v1/stories/${storyId}/detective`).catch(() => null);
  if (!c) return null;
  return (
    <aside className="card" aria-label="Detective mode (speculation)" style={{ borderStyle: "dashed", width: 320 }}>
      <Kicker>Detective mode · speculation</Kicker>
      <p role="note"><strong>{c.disclaimer}</strong></p>
      <p className="muted" style={{ fontSize: 13 }}>
        {c.counts.open} open · {c.resolved} resolved ({c.counts.supported} happened, {c.counts.contradicted} did not, {c.counts.expired} expired).
        {c.brier !== null && ` Brier ${c.brier.toFixed(2)} (a coin scores ${c.brier_coin}; lower is better).`}
      </p>
      {c.calibration.length > 0 && (
        <p className="muted" style={{ fontSize: 12 }}>
          {c.calibration.map((b) => `Said ${Math.round(b.band[0] * 100)}–${Math.round(b.band[1] * 100)}%: happened ${Math.round(b.happened * 100)}% of ${b.n}`).join(" · ")}
        </p>
      )}
      {c.predictions.length ? c.predictions.map((p) => (
        <div key={p.id} style={{ marginTop: 12 }}>
          <p>{p.text}</p>
          {p.probability !== null && (
            <div aria-label={`Model's probability ${Math.round(p.probability * 100)}%`} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div className="bar" style={{ flex: 1 }}><i style={{ width: `${p.probability * 100}%` }} /></div>
              <span className="kicker">{Math.round(p.probability * 100)}%</span>
            </div>
          )}
          <p className="muted" style={{ fontSize: 13 }}>
            Guessed {day(p.made_at)}, expected by {day(p.expected_by)} · {STATUS[p.status]}
          </p>
          <p className="muted" style={{ fontSize: 13 }}>Would confirm: {p.confirm_if} · Would refute: {p.refute_if}</p>
          {p.evidence.length > 0 && (
            <p className="muted" style={{ fontSize: 13 }}>Matched by: {p.evidence.map((g) => <a key={g} href={`/nodes/${g}`} style={{ marginRight: 6 }}>claim group</a>)}</p>
          )}
        </div>
      )) : <p className="muted">No guesses yet. They are made during the nightly run.</p>}
      {c.domains && c.domains.length > 0 && (
        <p className="muted" style={{ fontSize: 13, marginTop: 12 }}>
          Directions: {c.domains.map((d) => <Link key={d.id} href={`/directions/${encodeURIComponent(d.id)}`} style={{ marginRight: 8 }}>{d.label}</Link>)}
        </p>
      )}
    </aside>
  );
}
