// Pure helpers for the Today page: the "since" window, one list of new items, sections and counts.
import { count, perspectiveName } from "./format";
import type { Anomaly, NewEvent, StoryCard, Today } from "./types";

export type Mode = "visit" | "24h" | "7d";
const DAY = 86400000;

/** ISO time to ask the API for. A returning reader's last visit is capped at 14 days. */
export function sinceFor(mode: Mode, lastVisit: string | null, now = Date.now()): string {
  const ago = (d: number) => new Date(now - d * DAY).toISOString();
  if (mode === "24h") return ago(1);
  if (mode === "7d") return ago(7);
  const t = lastVisit ? Date.parse(lastVisit) : NaN;
  if (Number.isNaN(t)) return ago(1);
  return new Date(Math.max(t, now - 14 * DAY)).toISOString();
}

export type Kind = "event" | "conflict" | "perspective" | "claim" | "anomaly";
export const KIND_TAG: Record<Kind, string> = {
  event: "New event", conflict: "New conflict", perspective: "Now also reported from", claim: "New claim", anomaly: "New anomaly",
};
export type Item = {
  key: string; kind: Kind; tag: string; text: string; storyId: string; storyTitle: string; beat: string;
  href: string; perspectives: string[]; at: string | null; provisional?: boolean;
};

/** Every new thing once, as one row shape. Story names and beats come from the story list. */
export function items(t: Today, stories: StoryCard[]): Item[] {
  const by = new Map(stories.map((s) => [s.id, s]));
  const info = (id: string) => ({ storyTitle: by.get(id)?.title ?? "Story", beat: by.get(id)?.beat ?? "" });
  const out = new Map<string, Item>();
  for (const e of t.new_events as NewEvent[]) {
    out.set(`e:${e.id}`, { key: `e:${e.id}`, kind: "event", tag: KIND_TAG.event, text: e.label ?? "Untitled event", storyId: e.story_id, storyTitle: e.title, beat: e.beat, href: `/s/${e.story_id}/e/${e.id}`, perspectives: e.perspectives, at: e.first_seen });
  }
  for (const n of t.whats_new ?? []) {
    const kind: Kind = n.kind === "new_conflict" ? "conflict" : n.kind === "gained_perspective" ? "perspective" : "claim";
    const tag = kind === "perspective" ? `${KIND_TAG.perspective} ${n.perspectives.map(perspectiveName).join(", ")}` : KIND_TAG[kind];
    const key = `${kind}:${n.event_id}:${n.text}`;
    out.set(key, { key, kind, tag, text: n.text, storyId: n.story_id, ...info(n.story_id), href: `/s/${n.story_id}/e/${n.event_id}`, perspectives: n.perspectives, at: null });
  }
  for (const a of t.new_anomalies as Anomaly[]) {
    const sid = a.story_id ?? "";
    out.set(`a:${a.id}`, { key: `a:${a.id}`, kind: "anomaly", tag: KIND_TAG.anomaly, text: a.summary, storyId: sid, ...info(sid), href: a.event_id ? `/s/${sid}/e/${a.event_id}` : `/s/${sid}`, perspectives: (a.evidence ?? []).map((e) => e.perspective), at: a.since, provisional: a.status === "provisional" });
  }
  return [...out.values()];
}

export type Section = { id: "yours" | "other"; title: string; stories: { storyId: string; title: string; items: Item[] }[] };

/** Followed stories first, each as one block; everything else after. Newest first within a story. */
export function sections(all: Item[], follows: string[]): Section[] {
  const mk = (id: Section["id"], title: string, list: Item[]): Section => {
    const m = new Map<string, Item[]>();
    for (const i of list) m.set(i.storyId, [...(m.get(i.storyId) ?? []), i]);
    const stories = [...m.entries()].map(([storyId, its]) => ({ storyId, title: its[0].storyTitle, items: its.sort((a, b) => (b.at ?? "").localeCompare(a.at ?? "")) }));
    return { id, title, stories };
  };
  const mine = all.filter((i) => follows.includes(i.beat));
  const rest = all.filter((i) => !follows.includes(i.beat));
  return [mk("yours", "Your stories", mine), mk("other", follows.length ? "Other stories" : "Top stories", rest)].filter((s) => s.stories.length);
}

const LABEL: [Kind, string, string?][] = [["event", "new event"], ["conflict", "new conflict"], ["perspective", "gained perspective", "gained perspectives"], ["claim", "new claim"], ["anomaly", "anomaly", "anomalies"]];

/** "5 new events, 1 new conflict, 2 anomalies in 3 stories". Counts are of the rows. */
export function summary(all: Item[]): { parts: [Kind, string][]; text: string } {
  const parts = LABEL.map(([k, one, many]) => [k, all.filter((i) => i.kind === k).length, one, many] as const)
    .filter(([, n]) => n > 0).map(([k, n, one, many]): [Kind, string] => [k, count(n, one, many)]);
  const stories = new Set(all.map((i) => i.storyId)).size;
  return { parts, text: parts.length ? `${parts.map((p) => p[1]).join(", ")} in ${count(stories, "story", "stories")}` : "" };
}

/** The newest collected report across public stories: tells a quiet period from a stalled one. */
export const lastCollected = (stories: StoryCard[]): string | null =>
  stories.map((s) => s.last_report_at).filter((x): x is string => !!x).sort().pop() ?? null;
