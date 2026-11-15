"use client";
import { useEffect, useRef, useState } from "react";
import { Kicker } from "@/components/bits";
import Status from "@/components/Status";
import { pullPrefs, signIn, signOut, signedInAs, takeLapsed } from "@/lib/account";
import { perspectiveLabel } from "@/lib/format";
import { authMessage } from "@/lib/messages";
import { DEFAULTS, loadPrefs, savePrefs, type Prefs } from "@/lib/prefs";

type Card = { id: string; title: string; beat: string; beat_name?: string; perspectives: string[] };

function Account({ who, onChange }: { who: string | null; onChange: (prefs?: Partial<Prefs>) => void }) {
  const [cred, setCred] = useState({ email: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { if (takeLapsed()) setError("Signed out. Sign in again to sync."); }, []);
  const enter = async (create: boolean) => {
    if (busy) return;
    setBusy(true); setError("");
    try {
      await signIn(cred.email, cred.password, create);
      onChange((await pullPrefs()) ?? {});
    } catch (e) { setError(authMessage(e)); }
    setBusy(false);
  };
  if (who) {
    return (
      <p>Signed in as {who}. Your choices sync across devices. <button type="button" onClick={() => { signOut(); onChange(); }}>Sign out</button></p>
    );
  }
  return (
    <form onSubmit={(e) => { e.preventDefault(); void enter(false); }} aria-label="Account">
      <p className="muted">Optional. Guests keep everything in this browser.</p>
      <p><label htmlFor="acct-email" className="kicker">Email</label><br />
        <input id="acct-email" type="email" autoComplete="email" required value={cred.email} onChange={(e) => setCred({ ...cred, email: e.target.value })} /></p>
      <p><label htmlFor="acct-pw" className="kicker">Password</label><br />
        <input id="acct-pw" type="password" autoComplete="current-password" required minLength={6} value={cred.password} onChange={(e) => setCred({ ...cred, password: e.target.value })} /></p>
      <p className="row">
        <button type="submit" disabled={busy}>{busy ? "Working" : "Sign in"}</button>
        <button type="button" disabled={busy} onClick={() => void enter(true)}>Create account</button>
        <Status kind="error">{error}</Status>
      </p>
    </form>
  );
}

export default function Welcome() {
  const [prefs, setPrefs] = useState<Prefs>(DEFAULTS);
  const [stories, setStories] = useState<Card[]>([]);
  const [who, setWho] = useState<string | null>(null);
  const [status, setStatus] = useState<{ kind: "ok" | "error"; text: string }>({ kind: "ok", text: "" });
  const loaded = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    setWho(signedInAs());
    setPrefs(loadPrefs());
    loaded.current = true;
    fetch("/api/v1/stories").then((r) => (r.ok ? r.json() : [])).then(setStories).catch(() => setStories([]));
  }, []);

  // Changes save themselves a moment after the last one; there is no Save button.
  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    if (!loaded.current) return;
    clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      savePrefs(prefs);
      const email = prefs.email || who || "";
      if (prefs.frequency !== "never" && email.includes("@")) {
        try {
          const r = await fetch("/api/v1/subscription", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, frequency: prefs.frequency, follows: prefs.follows }) });
          if (!r.ok) return setStatus({ kind: "error", text: "Saved here, but the digest could not be set up. Check the email address." });
        } catch { return setStatus({ kind: "error", text: "Saved here, but the digest could not be set up. Check your connection." }); }
      }
      setStatus({ kind: "ok", text: "Saved" });
    }, 600);
    return () => clearTimeout(timer.current);
  }, [prefs, who]);

  const regions = [...new Set(stories.flatMap((s) => s.perspectives))].sort();
  const beats = [...new Map(stories.map((s) => [s.beat, s.beat_name ?? s.title])).entries()];
  const toggle = (k: "regions" | "follows", v: string) =>
    setPrefs((p) => ({ ...p, [k]: p[k].includes(v) ? p[k].filter((x) => x !== v) : [...p[k], v] }));
  return (
    <>
      <Kicker>Welcome</Kicker>
      <h1>Following and preferences</h1>
      <p className="muted">Stays in this browser unless you sign in. Nothing is tracked. Changes ordering and what the digest covers, never what is hidden.</p>
      <Kicker>Account</Kicker>
      <Account who={who} onChange={(remote) => {
        setWho(signedInAs());
        if (remote && Object.keys(remote).length) { const merged = { ...DEFAULTS, ...remote }; savePrefs(merged); setPrefs(merged); }
      }} />
      <form onSubmit={(e) => e.preventDefault()} aria-label="Preferences">
        <Kicker>Stories you follow</Kicker>
        {beats.length ? (
          <div className="row">
            {beats.map(([b, t]) => (
              <button type="button" key={b} aria-pressed={prefs.follows.includes(b)} className={`pill${prefs.follows.includes(b) ? " on" : ""}`} onClick={() => toggle("follows", b)}>{t}</button>
            ))}
          </div>
        ) : <p className="muted">No public stories yet. Once there are, you can follow them here.</p>}
        {regions.length > 0 && <>
          <Kicker>Perspectives you want to see first</Kicker>
          <div className="row">
            {regions.map((r) => (
              <button type="button" key={r} aria-pressed={prefs.regions.includes(r)} className={`pill${prefs.regions.includes(r) ? " on" : ""}`} onClick={() => toggle("regions", r)}>{perspectiveLabel(r)}</button>
            ))}
          </div>
        </>}
        <Kicker>Email digest</Kicker>
        <div className="row">
          {(["daily", "weekly", "never"] as const).map((f) => (
            <label key={f}><input type="radio" name="freq" checked={prefs.frequency === f} onChange={() => setPrefs({ ...prefs, frequency: f })} /> {f}</label>
          ))}
        </div>
        {prefs.frequency !== "never" && (
          <p><label className="kicker" htmlFor="email">Send the digest to</label><br />
            <input id="email" type="email" placeholder={who ?? ""} value={prefs.email ?? ""} onChange={(e) => setPrefs({ ...prefs, email: e.target.value })} />
            {who && !prefs.email && <span className="muted fs13"> Uses your account email, {who}.</span>}</p>
        )}
        <Status kind={status.kind}>{status.text}</Status>
      </form>
    </>
  );
}
