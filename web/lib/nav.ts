// Which header section a path belongs to, so the current page is marked on every route.
export const SECTIONS: { href: string; label: string; match: (p: string) => boolean }[] = [
  { href: "/today", label: "Today", match: (p) => p === "/today" },
  { href: "/stories", label: "Stories", match: (p) => p === "/stories" || /^\/(s|d|nodes|people|directions)(\/|$)/.test(p) },
  { href: "/", label: "World", match: (p) => p === "/" || p === "/world" },
  { href: "/sources", label: "Sources", match: (p) => p === "/sources" || p.startsWith("/sources/") },
  { href: "/ask", label: "Ask", match: (p) => p === "/ask" },
];

export const sectionOf = (path: string): string | null => SECTIONS.find((s) => s.match(path))?.href ?? null;
