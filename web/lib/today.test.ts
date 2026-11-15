import { describe, expect, it } from "vitest";
import { items, sections, sinceFor, summary } from "./today";
import type { StoryCard, Today } from "./types";

const NOW = Date.parse("2026-11-14T12:00:00Z");
const story = (id: string, beat: string) => ({ id, title: `Story ${id}`, beat }) as StoryCard;
const t = {
  since: "x", day: null, changes: [], breaking: [], blind_spots: [], followed: [],
  new_events: [{ id: "e1", story_id: "s1", title: "Story s1", beat: "b1", label: "Talks", first_seen: "2026-11-14T10:00:00Z", perspectives: ["KE"] }, { id: "e2", story_id: "s2", title: "Story s2", beat: "b2", label: null, first_seen: "2026-11-14T09:00:00Z", perspectives: [] }],
  whats_new: [{ kind: "new_conflict", story_id: "s1", event_id: "e1", text: "Count", perspectives: [] }, { kind: "new_conflict", story_id: "s1", event_id: "e1", text: "Count", perspectives: [] }],
  new_anomalies: [{ id: "a1", story_id: "s2", event_id: "e2", summary: "x", since: "2026-11-14T11:00:00Z", status: "active", evidence: [] }],
} as unknown as Today;

describe("sinceFor", () => {
  it("uses the last visit, capped at 14 days, else 24 hours", () => {
    expect(sinceFor("visit", "2026-11-14T11:00:00Z", NOW)).toBe("2026-11-14T11:00:00.000Z");
    expect(sinceFor("visit", "2026-11-11T12:00:00Z", NOW)).toBe("2026-11-11T12:00:00.000Z"); // three days
    expect(sinceFor("visit", "2026-09-01T00:00:00Z", NOW)).toBe("2026-10-31T12:00:00.000Z");
    expect(sinceFor("visit", null, NOW)).toBe("2026-11-13T12:00:00.000Z");
    expect(sinceFor("7d", "2026-11-14T11:00:00Z", NOW)).toBe("2026-11-07T12:00:00.000Z");
  });
});

describe("items, sections, summary", () => {
  const all = items(t, [story("s1", "b1"), story("s2", "b2")]);
  it("lists each new item once", () => expect(all.map((i) => i.key).sort()).toEqual(["a:a1", "conflict:e1:Count", "e:e1", "e:e2"]));
  it("puts followed stories first", () => {
    const s = sections(all, ["b2"]);
    expect(s.map((x) => x.id)).toEqual(["yours", "other"]);
    expect(s[0].stories[0].storyId).toBe("s2");
  });
  it("has only top stories when nothing is followed", () => expect(sections(all, []).map((s) => s.title)).toEqual(["Top stories"]));
  it("summary counts match the rows", () => {
    const sm = summary(all);
    expect(sm.text).toBe("2 new events, 1 new conflict, 1 anomaly in 2 stories");
    const rows = sections(all, []).flatMap((s) => s.stories.flatMap((x) => x.items));
    expect(rows).toHaveLength(4);
    expect(rows.filter((r) => r.kind === "event")).toHaveLength(2);
  });
});
