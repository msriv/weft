// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Dock from "./Dock";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Dock", () => {
  it("opens and closes the Ask panel and keeps it mounted", () => {
    render(<Dock storyId="s1" speculation={null} />);
    const tab = screen.getByRole("button", { name: "Ask" });
    expect(tab.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("button", { name: "Speculation" })).toBeNull(); // detective mode off
    fireEvent.click(tab);
    expect(tab.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("region", { name: "Ask about this story" })).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(tab.getAttribute("aria-expanded")).toBe("false");
  });

  it("shows Speculation only when it has content, and one panel at a time", () => {
    render(<Dock storyId="s1" speculation={<p>Model speculation, not reporting</p>} />);
    fireEvent.click(screen.getByRole("button", { name: "Speculation" }));
    expect(screen.getByRole("region", { name: "Speculation about this story" }).hasAttribute("hidden")).toBe(false);
    expect(document.getElementById("dock-panel-ask")?.hasAttribute("hidden")).toBe(true);
  });

  it("sends the story id with the question", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ sentences: [], cites: [], note: "No source in our coverage answers this." }) });
    vi.stubGlobal("fetch", fetchMock);
    render(<Dock storyId="kessar-strait" speculation={null} />);
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "who reported it?" } });
    fireEvent.submit(screen.getByLabelText("Question").closest("form")!);
    await screen.findByText(/No source in our coverage/);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ question: "who reported it?", story_id: "kessar-strait" });
  });
});
