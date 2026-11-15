// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AnomalyFeedback from "./AnomalyFeedback";
import LiveFeed from "./LiveFeed";

afterEach(cleanup);

class FakeSource {
  static last: FakeSource;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  handlers: Record<string, (e: MessageEvent) => void> = {};
  closed = false;
  constructor(public url: string) { FakeSource.last = this; }
  addEventListener(type: string, fn: (e: MessageEvent) => void) { this.handlers[type] = fn; }
  close() { this.closed = true; }
  emit(type: string, data: object) { this.handlers[type](new MessageEvent(type, { data: JSON.stringify(data) })); }
}

describe("LiveFeed", () => {
  beforeEach(() => { vi.stubGlobal("EventSource", FakeSource); });

  it("waits, shows connection state, and lists a new report with a link to the original", () => {
    const { unmount } = render(<LiveFeed storyId="harbour-fire" />);
    expect(FakeSource.last.url).toBe("/api/v1/stories/harbour-fire/stream");
    expect(screen.getByText(/Waiting for new reports/)).toBeTruthy();
    expect(screen.getByText(/reconnecting/)).toBeTruthy();
    act(() => FakeSource.last.onopen?.());
    expect(screen.getByText(/connected/)).toBeTruthy();
    act(() => FakeSource.last.emit("node.added", { id: "r1", title: "Port closed", source: "Fictional Daily", url: "https://x.test/1" }));
    expect(screen.getByText("Port closed").getAttribute("href")).toBe("/nodes/r1");
    expect(screen.getByText("Original ↗").getAttribute("rel")).toBe("noopener noreferrer");
    unmount();
    expect(FakeSource.last.closed).toBe(true);
  });

  it("marks a provisional anomaly as provisional", () => {
    render(<LiveFeed storyId="s" />);
    act(() => FakeSource.last.emit("anomaly.updated", { id: "a1", status: "provisional", summary: "Counts differ" }));
    expect(screen.getByText("provisional")).toBeTruthy();
    expect(screen.getByText("Counts differ")).toBeTruthy();
  });
});

describe("AnomalyFeedback", () => {
  const signedIn = (admin: boolean) => {
    const store: Record<string, string> = { "weft:session": JSON.stringify({ idToken: "t", refreshToken: "r", email: "e@x.test", expiresAt: Date.now() + 1e6 }) };
    vi.stubGlobal("localStorage", { getItem: (k: string) => store[k] ?? null, setItem: () => {}, removeItem: () => {} });
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}`);
      return new Response("{}", { status: url.endsWith("/admin/me") && !admin ? 403 : 200 });
    }));
    return calls;
  };

  it("shows nothing to a reader who is not an editor", async () => {
    signedIn(false);
    const { container } = render(<AnomalyFeedback id="a1" />);
    await act(async () => { await Promise.resolve(); });
    expect(container.textContent).toBe("");
  });

  it("lets an editor label an anomaly and then shows the label", async () => {
    const calls = signedIn(true);
    render(<AnomalyFeedback id="a1" />);
    const useful = await screen.findByText("Useful");
    act(() => useful.click());
    await waitFor(() => expect(screen.getByText(/Owner label: useful/)).toBeTruthy());
    expect(calls).toContain("POST /api/admin/anomalies/a1/feedback");
  });
});
