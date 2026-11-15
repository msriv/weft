// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import ClaimMatrix from "./ClaimMatrix";
import type { EventPage } from "@/lib/types";

afterEach(cleanup);

const rep = (id: string, name: string) => ({ id, url: `https://x.example/${id}`, published_at: "2026-11-10T08:00:00Z", source: { name } });
const e = {
  perspectives: { AL: [rep("r1", "Aldoria Daily")], VE: [rep("r2", "Veymar Wire")] },
  claim_groups: [
    { id: "a", label: "Twelve vessels", perspectives: ["AL"], n_reports: 1, claims: [{ report_id: "r1", text: "Twelve vessels were detained.", start: 0, end: 5 }] },
    { id: "b", label: "Nine vessels", perspectives: ["VE"], n_reports: 1, claims: [{ report_id: "r2", text: "Nine vessels were held.", start: 0, end: 5 }] },
  ],
  conflicts: [{ groups: ["a", "b"], nli_score: 0.9 }], figures: [],
} as unknown as EventPage;

describe("ClaimMatrix", () => {
  it("exposes filled and empty cells as text", () => {
    render(<ClaimMatrix e={e} />);
    expect(screen.getAllByLabelText(/sentence found in/).length).toBe(2);
    expect(screen.getAllByLabelText(/No sentence found from/).length).toBe(2); // wording is a gap in coverage, not a denial
  });
  it("opens the sentence on click and closes it with Escape, without leaving the page", () => {
    render(<ClaimMatrix e={e} />);
    fireEvent.click(screen.getByLabelText(/Aldoria Daily: sentence found/));
    expect(screen.getByRole("region", { name: /Sentence behind/ }).textContent).toContain("Twelve vessels were detained.");
    expect(screen.getByText("Source article").getAttribute("href")).toBe("https://x.example/r1");
    fireEvent.keyDown(screen.getByRole("region", { name: /Sentence behind/ }), { key: "Escape" });
    expect(screen.queryByRole("region", { name: /Sentence behind/ })).toBeNull();
  });
  it("filters rows", () => {
    render(<ClaimMatrix e={e} />);
    fireEvent.click(screen.getByRole("button", { name: "One perspective only" }));
    expect(screen.getAllByRole("row").length).toBeGreaterThan(2);
    fireEvent.click(screen.getByRole("button", { name: "Conflicts" }));
    expect(screen.getAllByText("Conflict").length).toBe(2);
  });
});
