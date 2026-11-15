// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ClaimMatrix from "./ClaimMatrix";
import FollowButton from "./FollowButton";
import type { EventPage } from "@/lib/types";

afterEach(cleanup);

// Fictional places and outlets only.
const report = (id: string, name: string) => ({ id, source: { name } }) as unknown as EventPage["perspectives"][string][number];
const event = {
  perspectives: { AL: [report("r1", "Aldoria Daily")], VE: [report("r2", "Veymar Wire")] },
  claim_groups: [{ id: "g1", label: "A bridge closed", perspectives: ["AL"], n_reports: 1, claims: [{ report_id: "r1", text: "The bridge closed.", start: 0, end: 18 }] }],
  figures: [],
} as unknown as EventPage;

describe("ClaimMatrix", () => {
  it("fills the cell for the outlet that carries the claim and marks the other as no sentence found", () => {
    render(<ClaimMatrix e={event} />);
    expect(screen.getByLabelText("Aldoria Daily: The bridge closed.")).toBeTruthy();
    expect(screen.getByLabelText("No sentence from Veymar Wire")).toBeTruthy();
  });
  it("says so when nothing was extracted", () => {
    render(<ClaimMatrix e={{ ...event, claim_groups: [] }} />);
    expect(screen.getByText(/No claims extracted/)).toBeTruthy();
  });
});

describe("FollowButton", () => {
  beforeEach(() => {
    const store: Record<string, string> = {};
    vi.stubGlobal("localStorage", { getItem: (k: string) => store[k] ?? null, setItem: (k: string, v: string) => { store[k] = v; } });
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}")));
  });
  it("toggles and remembers the beat", () => {
    const { unmount } = render(<FollowButton beat="bridge" />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("button").getAttribute("aria-pressed")).toBe("true");
    unmount();
    render(<FollowButton beat="bridge" />);
    expect(screen.getByRole("button").textContent).toBe("Following");
  });
});
