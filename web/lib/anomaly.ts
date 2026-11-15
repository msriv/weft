// Plain-words text and grouping for anomaly cards. Wording is coverage language only (rule 1):
// it says what was compared, never which side is right.
import type { Anomaly } from "./types";
import { perspectiveLabel } from "./format";

export const FOOTER = "A written rule compared these reports with each other. It does not say which is right.";

const str = (v: unknown) => (typeof v === "string" ? v : "");

/** One plain sentence per rule. Every rule has a template; unknown rules fall back to the stored summary. */
export function sentence(a: Pick<Anomaly, "rule" | "detail" | "summary">): string {
  const d = a.detail ?? {};
  switch (a.rule) {
    case "omission":
      return str(d.perspective)
        ? `Reports from ${perspectiveLabel(str(d.perspective))} do not carry a claim that other perspectives report.`
        : "A claim that most reports carry is missing from one perspective.";
    case "numbers_differ": return "Outlets give different numbers for the same thing.";
    case "figure_revised": return "An outlet later gave a figure outside the range of its own first report.";
    case "silence": return "An outlet that usually covers this story has not published on it recently.";
    case "copied_text": return "Several outlets published near-identical text.";
    case "silent_edit": return "A report's text changed after it was published, with no note on the page.";
    case "loaded_wording": return str(d.term) ? `One outlet uses the word “${str(d.term)}” far more than others covering the same event.` : "One outlet uses a word far more than others covering the same event.";
    case "unattributed": return "A claim appears with no named source.";
    case "anonymous_sourcing": return "Some reports name who said this claim and others cite only unnamed sources.";
    case "single_origin": return "Many reports of this claim trace back to one speaker.";
    case "conflicting_accounts": return "Two groups of reports give accounts that cannot both be as written.";
    case "quote_differs": return "A report's quote differs from the text its speaker issued.";
    default: return a.summary;
  }
}

export const RULES_WITH_TEMPLATE = ["omission", "numbers_differ", "figure_revised", "silence", "copied_text", "silent_edit", "loaded_wording", "unattributed", "anonymous_sourcing", "single_origin", "conflicting_accounts", "quote_differs"];

/** At most four evidence chips, then how many more. */
export function chips<T>(items: T[], max = 4): { shown: T[]; more: number } {
  return { shown: items.slice(0, max), more: Math.max(0, items.length - max) };
}

/** Newest first, optionally one rule, grouped by event (groups ordered by their newest anomaly). */
export function groupByEvent<T extends Pick<Anomaly, "id" | "rule" | "event_id" | "since">>(items: T[], kind?: string): [string, T[]][] {
  const sorted = items.filter((a) => !kind || a.rule === kind).sort((x, y) => y.since.localeCompare(x.since));
  const m = new Map<string, T[]>();
  for (const a of sorted) m.set(a.event_id ?? "", [...(m.get(a.event_id ?? "") ?? []), a]);
  return [...m.entries()];
}

export function kindCounts(items: Pick<Anomaly, "rule">[]): [string, number][] {
  const m = new Map<string, number>();
  for (const a of items) m.set(a.rule, (m.get(a.rule) ?? 0) + 1);
  return [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}
