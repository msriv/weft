"use client";
import { useState } from "react";

export default function ReportProblem({ refId, kind, label }: { refId?: string; kind: string; label: string }) {
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState("");
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "busy" | "sent" | "error">("idle");
  if (!open) return <p><button onClick={() => setOpen(true)}>{label}</button></p>;
  return (
    <form
      className="card"
      onSubmit={async (e) => {
        e.preventDefault();
        if (state === "busy") return;
        setState("busy");
        try {
          const r = await fetch("/api/v1/reports-problem", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ kind, ref_id: refId, message: msg, email: email || null }),
          });
          setState(r.ok ? "sent" : "error");
        } catch { setState("error"); }
      }}
    >
      {state === "sent" ? <p>Thank you. An editor will look at it, and fixes appear in the corrections log on How we weigh.</p> : (
        <>
          <label htmlFor="msg" className="kicker">What looks wrong?</label>
          <textarea id="msg" required minLength={3} maxLength={2000} rows={4} className="w100" value={msg} onChange={(e) => setMsg(e.target.value)} />
          <label htmlFor="em" className="kicker">Email, only if you want a reply (optional)</label>
          <input id="em" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <div className="row"><button type="submit" disabled={state === "busy"}>{state === "busy" ? "Sending" : "Send"}</button><button type="button" onClick={() => setOpen(false)}>Cancel</button></div>
          {state === "error" && <p role="alert">Could not send. Check your connection and try again.</p>}
        </>
      )}
    </form>
  );
}
