import { Kicker } from "@/components/bits";
import { api } from "@/lib/api";
import { day } from "@/lib/format";

type Prediction = {
  id: string; text: string; expected_by: string; confirm_if: string; refute_if: string;
  made_at: string; status: "open" | "supported" | "contradicted" | "expired";
};
type Card = {
  disclaimer: string; predictions: Prediction[]; hit_rate: number | null;
  counts: Record<Prediction["status"], number>;
};

const STATUS: Record<Prediction["status"], string> = {
  open: "Open", supported: "Later reports support it", contradicted: "Later reports contradict it", expired: "Expired, nothing reported",
};

// Detective mode (D20): experimental speculation, off unless the API runs with DETECTIVE=on.
export default async function DetectivePanel({ storyId }: { storyId: string }) {
  const c = await api<Card>(`/v1/stories/${storyId}/detective`).catch(() => null);
  if (!c) return null;
  return (
    <aside className="card" aria-label="Detective mode (speculation)" style={{ borderStyle: "dashed", width: 320 }}>
      <Kicker anomaly>Detective mode · speculation</Kicker>
      <p role="note"><strong>{c.disclaimer}</strong></p>
      <p className="muted" style={{ fontSize: 13 }}>
        Checked so far: {c.counts.supported} supported, {c.counts.contradicted} contradicted, {c.counts.expired} expired, {c.counts.open} open.
        {c.hit_rate !== null && ` Hit rate ${Math.round(c.hit_rate * 100)}%.`}
      </p>
      {c.predictions.length ? c.predictions.map((p) => (
        <div key={p.id} style={{ marginTop: 12 }}>
          <p>{p.text}</p>
          <p className="muted" style={{ fontSize: 13 }}>
            Guessed {day(p.made_at)}, expected by {day(p.expected_by)} · {STATUS[p.status]}
          </p>
          <p className="muted" style={{ fontSize: 13 }}>Would confirm: {p.confirm_if} · Would refute: {p.refute_if}</p>
        </div>
      )) : <p className="muted">No guesses yet. They are made during the nightly run.</p>}
    </aside>
  );
}
