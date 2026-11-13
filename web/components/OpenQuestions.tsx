import { Kicker } from "@/components/bits";
import { api } from "@/lib/api";

type Q = { kind: string; event_id: string; question: string; would_change: string; groups: string[]; due?: string };

// Open questions (#111): fixed rules over the graph, no model. Each one leaves when its input arrives.
export default async function OpenQuestions({ storyId }: { storyId: string }) {
  const qs = await api<Q[]>(`/v1/stories/${storyId}/questions`).catch(() => null);
  if (!qs) return null;
  return (
    <aside className="card" aria-label="Open questions" style={{ width: 320 }}>
      <Kicker>Open questions</Kicker>
      <p className="muted" style={{ fontSize: 13 }}>What the coverage leaves open, found by written rules. Each question goes away when what would change it appears.</p>
      {qs.length ? qs.map((q, i) => (
        <div key={i} style={{ marginTop: 10 }}>
          <p style={{ margin: 0 }}><a href={`/s/${storyId}/e/${q.event_id}`}>{q.question}</a></p>
          <p className="muted" style={{ fontSize: 13, margin: "2px 0" }}>Would change the picture: {q.would_change}</p>
        </div>
      )) : <p className="muted">None right now.</p>}
    </aside>
  );
}
