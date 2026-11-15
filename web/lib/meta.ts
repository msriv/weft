import type { Metadata } from "next";

const NOTE = "Who reported what, from where. Weft does not say what is true.";

// Per-page title plus a coverage-language description (rule 1) and basic Open Graph tags.
export function meta(title: string | null | undefined, about: string): Metadata {
  const t = title || "Not found";
  const description = `${about} ${NOTE}`;
  return { title: t, description, openGraph: { title: t, description, type: "article", siteName: "Weft" } };
}
