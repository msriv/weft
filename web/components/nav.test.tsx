// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

let path = "/";
vi.mock("next/navigation", () => ({ usePathname: () => path }));
vi.mock("./Search", () => ({ default: () => null }));
import Nav from "./Nav";
import Breadcrumbs from "./Breadcrumbs";

afterEach(cleanup);

describe("Nav", () => {
  it.each([["/s/kessar-strait/e/e1", "Stories"], ["/sources/aldoria-post", "Sources"], ["/today", "Today"], ["/world", "World"], ["/ask", "Ask"]])(
    "marks the section for %s", (p, label) => {
      path = p;
      render(<Nav />);
      const current = screen.getAllByRole("link").filter((l) => l.getAttribute("aria-current") === "page");
      expect(current.map((l) => l.textContent)).toEqual([label]);
    });
  it("links to the preferences page from every route", () => {
    path = "/method";
    render(<Nav />);
    expect(screen.getByRole("link", { name: /Following and preferences/ }).getAttribute("href")).toBe("/welcome");
    expect(screen.queryAllByRole("link").some((l) => l.getAttribute("aria-current") === "page")).toBe(false);
  });
});

describe("Breadcrumbs", () => {
  it("shows titles, links the parents and marks the current page", () => {
    render(<Breadcrumbs items={[{ label: "Stories", href: "/stories" }, { label: "Vessels detained", href: "/s/x" }, { label: "Talks announced" }]} />);
    expect(screen.getByRole("link", { name: "Vessels detained" }).getAttribute("href")).toBe("/s/x");
    expect(screen.getByText("Talks announced").closest("li")?.getAttribute("aria-current")).toBe("page");
  });
});
