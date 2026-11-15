"use client";
import { useState } from "react";
import { Kicker } from "@/components/bits";
import Status from "@/components/Status";
import { askMessage, citeNumbers } from "@/lib/messages";

type Cite = { id: string; label: string; url?: string; quote: string; published_at?: string | null };
type Answer = { sentences: { text: string; cites: string[] }[]; cites: Cite[]; note?: string };
type Turn = { q: string; a: Answer };

const EXAMPLES = ["Which perspectives have reported on this story?", "What do the reports disagree on?", "Which countries have not published anything yet?"];

export default function Ask() {
  const [q, setQ] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [asked, setAsked] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [state, setState] = useState<"idle" | "busy" | "error">("idle");
  const [err, setErr] = useState("");
  const latest = turns[0]?.a ?? null;
  const nums = latest ? citeNumbers(latest.sentences) : new Map<string, number>();
  const cite = (id: string | null) => (id ? latest?.cites.find((c) => c.id === id) : undefined);
  const shown = cite(open) ?? cite([...nums.keys()][0] ?? null); // the first citation is open by default

  async function ask(question: string) {
    if (state === "busy" || question.trim().length < 3) return;
    setState("busy"); setErr(""); setOpen(null); setAsked(question);
    try {
      const r = await fetch("/api/v1/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }) });
      if (!r.ok) { setErr(askMessage(r.status)); return setState("error"); }
      const a = (await r.json()) as Answer;
      setTurns((t) => [{ q: question, a }, ...t]); setState("idle");
    } catch {
      setErr(askMessage(0)); setState("error");
    }
  }

  return (
    <>
      <Kicker>Ask</Kicker>
      <h1>Ask about the coverage</h1>
      <p className="muted">Answers say who reported what and link every statement to its source sentence. They never say what is true.</p>
      <form onSubmit={(e) => { e.preventDefault(); void ask(q); }}>
        <input aria-label="Question" className="w100" value={q} maxLength={500} required onChange={(e) => setQ(e.target.value)} placeholder="Which perspectives have reported on the strike?" />
        <p className="row">
          <button disabled={state === "busy"}>{state === "busy" ? "Reading sources" : "Ask"}</button>
          {!turns.length && state !== "busy" && EXAMPLES.map((x) => <button type="button" key={x} className="pill" onClick={() => { setQ(x); void ask(x); }}>{x}</button>)}
        </p>
      </form>
      {state === "busy" && <div role="status" aria-live="polite"><p className="muted">Reading sources for “{asked}”.</p><div className="card skeleton" aria-hidden="true">&nbsp;<br />&nbsp;<br />&nbsp;</div></div>}
      {state === "error" && <p role="alert">{err} <button type="button" onClick={() => void ask(asked)}>Try again</button></p>}
      {turns.map((t, ti) => (
        <section key={ti} aria-label={`Answer to: ${t.q}`}>
          <Kicker>{t.q}</Kicker>
          <div className="row ifs">
            <div className="flex2">
              {t.a.sentences.map((s, i) => (
                <p key={i}>{s.text} {s.cites.map((c) => { const n = citeNumbers(t.a.sentences).get(c); return ti === 0
                  ? <button key={c} className="pill" aria-pressed={shown?.id === c} onClick={() => setOpen(c)}>[{n}]</button>
                  : <span key={c} className="muted">[{n}]</span>; })}</p>
              ))}
              {t.a.note && <p className="muted">{t.a.note}</p>}
            </div>
            {ti === 0 && (
              <aside className="card flex1" aria-live="polite">
                <Kicker>Evidence</Kicker>
                {shown ? (
                  <>
                    <b>[{nums.get(shown.id)}] {shown.label}</b>{shown.published_at && <span className="muted"> · {shown.published_at.slice(0, 10)}</span>}
                    <blockquote>{shown.quote}</blockquote>
                    {shown.url && <a href={shown.url} rel="noopener noreferrer">Open source</a>}
                  </>
                ) : <p className="muted">This answer cites no sources.</p>}
              </aside>
            )}
          </div>
        </section>
      ))}
    </>
  );
}
