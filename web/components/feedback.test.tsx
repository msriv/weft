// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Ask from "@/app/ask/page";
import Welcome from "@/app/welcome/page";
import FollowButton from "./FollowButton";
import ReportProblem from "./ReportProblem";

beforeEach(() => localStorage.clear());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Welcome sign-in", () => {
  it("signs in on Enter, disables while working, and shows a readable error", async () => {
    let resolve!: (r: unknown) => void;
    const f = vi.fn((u: string) => u.startsWith("/api/auth") ? new Promise((r) => { resolve = r; }) : Promise.resolve({ ok: true, json: async () => [] }));
    vi.stubGlobal("fetch", f);
    render(<Welcome />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@b.co" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret1" } });
    fireEvent.submit(screen.getByLabelText("Account")); // what Enter does
    await waitFor(() => expect((screen.getByText("Working") as HTMLButtonElement).disabled).toBe(true));
    expect(f.mock.calls.filter((c) => String(c[0]).startsWith("/api/auth"))).toHaveLength(1);
    resolve({ ok: false, json: async () => ({ error: "EMAIL_NOT_FOUND" }) });
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("That email and password do not match an account."));
    expect(document.body.textContent).not.toContain("EMAIL_NOT_FOUND");
  });
});

describe("Ask", () => {
  it("shows an error and a retry when the network is down", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    render(<Ask />);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "What happened?" } });
    fireEvent.submit(screen.getByLabelText("Question").closest("form")!);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Could not reach Weft"));
    expect((screen.getByRole("button", { name: "Ask" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText("Try again")).toBeTruthy();
  });
  it("numbers each source once across the answer and opens the first", async () => {
    const a = { sentences: [{ text: "One.", cites: ["x", "y"] }, { text: "Two.", cites: ["y"] }], cites: [{ id: "x", label: "Outlet X", quote: "qx" }, { id: "y", label: "Outlet Y", quote: "qy" }] };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => a }));
    render(<Ask />);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "What happened?" } });
    fireEvent.submit(screen.getByLabelText("Question").closest("form")!);
    await waitFor(() => expect(screen.getAllByText("[2]")).toHaveLength(2)); // sentence 1 and sentence 2 both point at Y
    expect(screen.getByText(/\[1\] Outlet X/)).toBeTruthy();
  });
});

describe("FollowButton", () => {
  it("says what following does once, with a link to manage it", () => {
    const { rerender } = render(<FollowButton beat="b" name="Kessar Strait" />);
    fireEvent.click(screen.getByText("Follow Kessar Strait"));
    expect(screen.getByRole("status").textContent).toContain("appear first on Today");
    expect(screen.getByText("Following and preferences")).toBeTruthy();
    fireEvent.click(screen.getByText("Following Kessar Strait")); // unfollow
    fireEvent.click(screen.getByText("Follow Kessar Strait"));
    expect(screen.getByRole("status").textContent).toBe(""); // told once only
    rerender(<FollowButton beat="b" name="Kessar Strait" />);
  });
});

describe("ReportProblem", () => {
  it("disables Send while sending", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(<ReportProblem kind="other" label="Report" />);
    fireEvent.click(screen.getByText("Report"));
    fireEvent.change(screen.getByLabelText("What looks wrong?"), { target: { value: "typo here" } });
    fireEvent.submit(screen.getByLabelText("What looks wrong?").closest("form")!);
    await waitFor(() => expect((screen.getByText("Sending") as HTMLButtonElement).disabled).toBe(true));
  });
});
