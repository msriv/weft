// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import TodayView from "./TodayView";
import type { StoryCard } from "@/lib/types";

const stories = [{ id: "s1", title: "Story one", beat: "b1", last_report_at: "2026-11-14T08:00:00Z" }, { id: "s2", title: "Story two", beat: "b2", last_report_at: null }] as StoryCard[];
const today = (extra = {}) => ({
  since: "x", day: null, changes: [], breaking: [], blind_spots: [], followed: [], whats_new: [], new_anomalies: [],
  new_events: [{ id: "e1", story_id: "s1", title: "Story one", beat: "b1", label: "Talks announced", first_seen: "2026-11-14T10:00:00Z", perspectives: ["KE"] }, { id: "e2", story_id: "s2", title: "Story two", beat: "b2", label: "Vote held", first_seen: "2026-11-14T09:00:00Z", perspectives: [] }],
  ...extra,
});
const calls: string[] = [];
beforeEach(() => {
  localStorage.clear(); calls.length = 0;
  vi.stubGlobal("fetch", vi.fn(async (u: string) => { calls.push(u); return { ok: true, json: async () => (calls.length > 0 && globalThis.__t) } as Response; }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
declare global { var __t: unknown; }

describe("TodayView", () => {
  it("shows followed stories first and counts that match the rows", async () => {
    globalThis.__t = today();
    localStorage.setItem("weft:prefs", JSON.stringify({ follows: ["b2"] }));
    const { container } = render(<TodayView stories={stories} />);
    await waitFor(() => expect(screen.getByText("2 new events in 2 stories")).toBeTruthy());
    expect(container.querySelectorAll("a.card")).toHaveLength(2);
    expect(container.querySelector("section")?.id).toBe("yours");
    expect(calls[0]).toContain("follow=b2");
  });
  it("sends the stored last visit as since", async () => {
    globalThis.__t = today();
    localStorage.setItem("weft:prefs", JSON.stringify({ last_visit: new Date(Date.now() - 3 * 86400000).toISOString() }));
    render(<TodayView stories={stories} />);
    await waitFor(() => expect(calls.length).toBe(1));
    expect(Date.now() - Date.parse(new URL(calls[0], "http://x").searchParams.get("since")!)).toBeGreaterThan(2.9 * 86400000);
    await waitFor(() => expect(screen.getAllByText(/Since your last visit/).length).toBeGreaterThan(0));
  });
  it("shows one empty state with the last collected time", async () => {
    globalThis.__t = today({ new_events: [] });
    render(<TodayView stories={stories} />);
    await waitFor(() => expect(screen.getByText(/Nothing new/)).toBeTruthy());
    expect(screen.getByText(/last report was collected/)).toBeTruthy();
  });
});
