"use client";
import { useEffect, useState } from "react";
import { DEFAULTS, loadPrefs, savePrefs, type Prefs } from "@/lib/prefs";
import { Kicker } from "@/components/bits";

type Card = { id: string; title: string; beat: string; perspectives: string[] };

export default function Welcome() {
  const [prefs, setPrefs] = useState<Prefs>(DEFAULTS);
  const [stories, setStories] = useState<Card[]>([]);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(false);
  useEffect(() => {
    setPrefs(loadPrefs());
    fetch("/api/v1/stories").then((r) => (r.ok ? r.json() : [])).then(setStories).catch(() => setStories([]));
  }, []);
  const regions = [...new Set(stories.flatMap((s) => s.perspectives))].sort();
  const beats = [...new Map(stories.map((s) => [s.beat, s.title])).entries()];
  const toggle = (k: "regions" | "follows", v: string) =>
    setPrefs((p) => ({ ...p, [k]: p[k].includes(v) ? p[k].filter((x) => x !== v) : [...p[k], v] }));
  return (
    <form onSubmit={async (e) => {
      e.preventDefault(); savePrefs(prefs); setSaved(false);
      if (prefs.frequency !== "never" && prefs.email) {
        const r = await fetch("/api/v1/subscription", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: prefs.email, frequency: prefs.frequency, follows: prefs.follows }) });
        if (!r.ok) return setError(true);
      }
      setError(false); setSaved(true);
    }}>
      <Kicker>Welcome</Kicker>
      <h1>What do you want to follow?</h1>
      <p className="muted">Stays in this browser. Nothing is tracked. Changes ordering and what the digest covers, never what is hidden.</p>
      <Kicker>Stories</Kicker>
      <div className="row">
        {beats.map(([b, t]) => (
          <button type="button" key={b} aria-pressed={prefs.follows.includes(b)} className={`pill${prefs.follows.includes(b) ? " on" : ""}`} onClick={() => toggle("follows", b)}>{t}</button>
        ))}
      </div>
      <Kicker>Perspectives you want to see first</Kicker>
      <div className="row">
        {regions.map((r) => (
          <button type="button" key={r} aria-pressed={prefs.regions.includes(r)} className={`pill${prefs.regions.includes(r) ? " on" : ""}`} onClick={() => toggle("regions", r)}>{r}</button>
        ))}
      </div>
      <Kicker>Email digest</Kicker>
      <div className="row">
        {(["daily", "weekly", "never"] as const).map((f) => (
          <label key={f}><input type="radio" name="freq" checked={prefs.frequency === f} onChange={() => setPrefs({ ...prefs, frequency: f })} /> {f}</label>
        ))}
      </div>
      {prefs.frequency !== "never" && (
        <p><label className="kicker" htmlFor="email">Email</label><br />
          <input id="email" type="email" value={prefs.email ?? ""} onChange={(e) => setPrefs({ ...prefs, email: e.target.value })} /></p>
      )}
      <p><button type="submit">Save</button> {saved && <span role="status">Saved.</span>}{error && <span role="alert">Could not subscribe. Check the email.</span>}</p>
    </form>
  );
}
