"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Empty, Kicker } from "@/components/bits";
import Time from "@/components/Time";
import { count, perspectiveName, date } from "@/lib/format";
import { loadPrefs, savePrefs } from "@/lib/prefs";
import { items, lastCollected, sections, sinceFor, summary, type Item, type Mode } from "@/lib/today";
import type { StoryCard, Today } from "@/lib/types";

const MODES: [Mode, string][] = [["visit", "Since your last visit"], ["24h", "Last 24 hours"], ["7d", "Last 7 days"]];

function Row({ i }: { i: Item }) {
  return (
    <Link href={i.href} className="card block">
      <div className="row fs13"><span className={`pill${i.kind === "anomaly" ? " anomaly" : ""}`}>{i.tag}</span>{i.provisional && <span className="pill">Provisional</span>}<span className="muted">{i.storyTitle}</span>{i.at && <span className="muted"><Time iso={i.at} relative /></span>}</div>
      <div className="my6">{i.text}</div>
      {i.perspectives.length > 0 && <div className="row fs12">{[...new Set(i.perspectives)].map((p) => <span className="pill" key={p}>{perspectiveName(p)}</span>)}</div>}
    </Link>
  );
}

export default function TodayView({ stories }: { stories: StoryCard[] }) {
  const [mode, setMode] = useState<Mode>("visit");
  const [last, setLast] = useState<string | null>(null);
  const [follows, setFollows] = useState<string[]>([]);
  const [t, setT] = useState<Today | null | undefined>(undefined);
  const [ready, setReady] = useState(false);
  useEffect(() => { const p = loadPrefs(); setLast(p.last_visit ?? null); setFollows(p.follows); setReady(true); }, []);
  const stamp = useCallback(() => savePrefs({ ...loadPrefs(), last_visit: new Date().toISOString() }), []);
  // leaving the page counts as having read it; the stored time is what the next visit compares with
  useEffect(() => { window.addEventListener("pagehide", stamp); return () => { window.removeEventListener("pagehide", stamp); stamp(); }; }, [stamp]);
  useEffect(() => {
    if (!ready) return;
    const q = new URLSearchParams({ since: sinceFor(mode, last) });
    follows.forEach((f) => q.append("follow", f));
    fetch(`/api/v1/today?${q}`).then((r) => (r.ok ? r.json() : null)).then(setT).catch(() => setT(null));
  }, [ready, mode, last, follows]);
  if (t === undefined) return <p className="muted" role="status">Loading what is new.</p>;
  if (t === null) return <p role="alert">Could not load what is new. Try again in a moment.</p>;
  const all = items(t, stories);
  const sm = summary(all);
  const secs = sections(all, follows);
  const collected = lastCollected(stories);
  const win = mode === "visit" ? (last ? `Since your last visit, ${date(last)}` : "Last 24 hours") : MODES.find(([m]) => m === mode)![1];
  return (
    <>
      <div className="row"><Kicker>{win}</Kicker>
        <span className="row fs13" role="group" aria-label="Time window">
          {MODES.filter(([m]) => m !== "visit" || last).map(([m, l]) => <button key={m} type="button" aria-pressed={mode === m} className={`pill${mode === m ? " on" : ""}`} onClick={() => setMode(m)}>{l}</button>)}
          {all.length > 0 && <button type="button" className="pill" onClick={() => { stamp(); setLast(new Date().toISOString()); setMode("visit"); }}>Mark all as read</button>}
        </span>
      </div>
      {sm.text ? <p id="summary">{sm.text}</p> : null}
      {all.length === 0 ? (
        <Empty>Nothing new in {follows.length ? "your stories" : "any story"} in this period.{collected ? <> The last report was collected <Time iso={collected} relative />, so quiet here is not a stalled collector.</> : null}</Empty>
      ) : secs.map((s) => (
        <section key={s.id} id={s.id} aria-label={s.title}>
          <Kicker>{s.title}</Kicker>
          {s.id === "other" && !follows.length && <p className="muted fs13">You follow no stories yet. Open a story and choose Follow to see it here first.</p>}
          {s.stories.map((st) => (
            <div className="stack" key={st.storyId}>
              <h3 className="m0"><Link href={`/s/${st.storyId}`}>{st.title}</Link></h3>
              {st.items.map((i) => <Row key={i.key} i={i} />)}
            </div>
          ))}
        </section>
      ))}
      {t.blind_spots.length > 0 && (
        <section id="gaps" aria-label="Coverage gaps">
          <Kicker>Coverage gaps (events of the last 48 hours)</Kicker>
          {t.blind_spots.map((b) => (
            <div className="card" key={b.event_id}>
              <Link href={`/s/${b.story_id}/e/${b.event_id}`}>{b.title}</Link>
              {b.no_source_published.length > 0 && <p className="muted">No source from {b.no_source_published.map(perspectiveName).join(", ")} has published on this event.</p>}
              {b.untracked.length > 0 && <p className="muted">Weft tracks no source from {b.untracked.map(perspectiveName).join(", ")}.</p>}
            </div>
          ))}
        </section>
      )}
      {t.directions && <p className="muted fs13"><Link href="/directions">{t.directions}</Link> (model speculation, not reporting).</p>}
      {t.changes.length > 0 && <p className="muted fs13">Updated overnight: {t.changes.map((c) => `${count(c.count, "item")} ${c.label.toLowerCase()}`).join(" · ")}.</p>}
    </>
  );
}
