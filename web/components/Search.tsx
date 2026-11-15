"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

type Hit = { id: string; title: string; story_id?: string };
type Results = Record<"stories" | "events" | "sources" | "people", Hit[]>;
const GROUPS: [keyof Results, string][] = [["stories", "Stories"], ["events", "Events"], ["sources", "Sources"], ["people", "People"]];
const href = (k: keyof Results, h: Hit) =>
  k === "stories" ? `/s/${h.id}` : k === "events" ? `/s/${h.story_id}/e/${h.id}` : k === "sources" ? `/sources/${h.id}` : `/people/${h.id}`;

/** Header search over public stories, events, sources and people. Press / to focus. */
export default function Search() {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<Results | null>(null);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(t.tagName) && !t.isContentEditable) { e.preventDefault(); input.current?.focus(); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  useEffect(() => {
    if (q.trim().length < 2) { setRes(null); return; }
    const t = setTimeout(() => {
      fetch(`/api/v1/search?q=${encodeURIComponent(q.trim())}`).then((r) => (r.ok ? r.json() : null)).then(setRes).catch(() => setRes(null));
    }, 200);
    return () => clearTimeout(t);
  }, [q]);
  const any = res && GROUPS.some(([k]) => res[k].length);
  return (
    <div className="search" role="search" onKeyDown={(e) => e.key === "Escape" && (setQ(""), input.current?.blur())}>
      <label className="sr-only" htmlFor="site-search">Search stories, events, sources and people</label>
      <input id="site-search" ref={input} type="search" placeholder="Search ( / )" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" />
      {res && (
        <div className="search-results card" role="region" aria-label="Search results" aria-live="polite">
          {!any && <p className="muted m0">No public story, event, source or person matches &ldquo;{q}&rdquo;.</p>}
          {GROUPS.map(([k, label]) => res[k].length > 0 && (
            <div key={k}>
              <div className="kicker">{label}</div>
              {res[k].map((h) => <div key={h.id}><Link href={href(k, h)} onClick={() => setQ("")}>{h.title}</Link></div>)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
