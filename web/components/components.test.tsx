// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FollowButton from "./FollowButton";

afterEach(cleanup);

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
