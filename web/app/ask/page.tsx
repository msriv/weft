"use client";
import { useState } from "react";
import { Kicker } from "@/components/bits";

type Cite = { id: string; label: string; url?: string; quote: string };
type Answer = { sentences: { text: string; cites: string[] }[]; cites: Cite[]; note?: string };

export default function Ask() {
  const [q, setQ] = useState("");
  const [a, setA] = useState<Answer | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [state, setState] = useState<"idle" | "busy" | "error">("idle");
  const cite = (id: string) => a?.cites.find((c) => c.id === id);
  return (
    <>
      <Kicker>Ask</Kicker>
      <h1>Ask about the coverage</h1>
      <p className="muted">Answers say who reported what and link every statement to its source sentence. They never say what is true.</p>
      <form onSubmit={async (e) => {
        e.preventDefault(); setState("busy"); setA(null); setOpen(null);
        const r = await fetch("/api/v1/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q }) });
        if (!r.ok) return setState("error");
        setA((await r.json()) as Answer); setState("idle");
      }}>
        <input aria-label="Question" style={{ width: "100%" }} value={q} maxLength={500} required onChange={(e) => setQ(e.target.value)} placeholder="Which perspectives have reported on the strike?" />
        <p><button disabled={state === "busy"}>{state === "busy" ? "Reading sources" : "Ask"}</button></p>
      </form>
      {state === "error" && <p role="alert">Could not answer. Try again.</p>}
      {a && (
        <div className="row" style={{ alignItems: "flex-start" }}>
          <div style={{ flex: 2 }}>
            {a.sentences.map((s, i) => (
              <p key={i}>{s.text} {s.cites.map((c, j) => <button key={c} className="pill" onClick={() => setOpen(c)}>[{j + 1}]</button>)}</p>
            ))}
            {a.note && <p className="muted">{a.note}</p>}
          </div>
          <aside className="card" style={{ flex: 1 }} aria-live="polite">
            <Kicker>Evidence</Kicker>
            {open && cite(open) ? (
              <>
                <b>{cite(open)!.label}</b>
                <blockquote>{cite(open)!.quote}</blockquote>
                {cite(open)!.url && <a href={cite(open)!.url} rel="noopener noreferrer">Open source</a>}
              </>
            ) : <p className="muted">Select a citation.</p>}
          </aside>
        </div>
      )}
    </>
  );
}
