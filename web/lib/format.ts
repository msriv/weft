import countries from "i18n-iso-countries";
import en from "i18n-iso-countries/langs/en.json";

countries.registerLocale(en);

/** Names that read better than the ISO long form. */
const SHORT: Record<string, string> = {
  US: "United States", GB: "United Kingdom", RU: "Russia", IR: "Iran", KR: "South Korea",
  KP: "North Korea", SY: "Syria", VE: "Venezuela", TZ: "Tanzania", MK: "North Macedonia", BO: "Bolivia", MD: "Moldova",
};

/**
 * Perspective code to a readable label. ISO country codes become short names; anything else
 * (an outlet group on a grouped beat, "unattributed", or a code we do not know) is shown as
 * words and never as a bare two-letter code.
 */
export function perspectiveLabel(code: string): string {
  if (!code || code === "unattributed") return "No country recorded";
  const up = code.toUpperCase();
  if (/^[A-Za-z]{2}$/.test(code)) return SHORT[up] ?? countries.getName(up, "en") ?? "Unknown country";
  return code.replace(/[-_]+/g, " ").replace(/^./, (c) => c.toUpperCase());
}
export const perspectiveName = perspectiveLabel;

/** Internal grouping key "2026-11-14" (UTC day). Never shown to readers: use `date`. */
export function day(iso: string | null): string {
  return iso ? iso.slice(0, 10) : "";
}

const utc = (iso: string, o: Intl.DateTimeFormatOptions) =>
  new Date(iso).toLocaleDateString("en-GB", { ...o, timeZone: "UTC" });
const dayOnly = (iso: string) => (/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00Z` : iso);

/** "14 Nov 2026". UTC, so server and browser agree. */
export const date = (iso: string | null): string =>
  iso ? utc(dayOnly(iso), { day: "numeric", month: "short", year: "numeric" }) : "";

/** "14 Nov". */
export const dateShort = (iso: string | null): string =>
  iso ? utc(dayOnly(iso), { day: "numeric", month: "short" }) : "";
export const shortDay = (iso: string): string => dateShort(iso);

/** "14 Nov 2026, 09:30 UTC". */
export const time = (iso: string | null): string => {
  if (!iso) return "";
  const t = new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
  return `${date(iso)}, ${t} UTC`;
};

export function ago(iso: string | null, now = Date.now()): string {
  if (!iso) return "";
  const m = Math.round((now - Date.parse(iso)) / 60000);
  if (m < 60) return `${Math.max(m, 0)} min ago`;
  if (m < 60 * 48) return `${Math.round(m / 60)} h ago`;
  return `${Math.round(m / 1440)} days ago`;
}

const nf = new Intl.NumberFormat("en-GB");
/** count(1, "report") is "1 report"; count(1200, "report") is "1,200 reports". */
export const count = (n: number, one: string, many = `${one}s`): string => `${nf.format(n)} ${n === 1 ? one : many}`;
export const num = (n: number): string => nf.format(n);

/** Beat id ("kessar-strait") as words, for when the API gave no name. */
export const beatLabel = (name: string | undefined, id: string): string =>
  name && name !== id ? name : id.replace(/[-_]+/g, " ").replace(/^./, (c) => c.toUpperCase());

export type RuleInfo = { name: string; does: string; params: Record<string, string> };

/** One table for rule names, plain descriptions and threshold labels. Shared by the method and evidence pages. */
export const RULES: Record<string, RuleInfo> = {
  omission: {
    name: "Omission", does: "A claim carried by most independent reports is missing from a perspective that has published enough on the event.",
    params: { min_share_of_event_reports: "Share of independent texts that carry the claim", min_perspective_origins: "Independent texts the silent perspective needs", min_perspective_sources: "Outlets the silent perspective needs", max_p_value: "Highest chance (p-value) that the gap is accidental", exclude_paywalled_sources: "Leave out paywalled sources" },
  },
  numbers_differ: {
    name: "Numbers differ", does: "Two reports give figures for the same thing that are further apart than their stated ranges allow.",
    params: { min_log_ratio: "Smallest gap between figures (log ratio)", max_hours_apart: "Most hours between the two reports" },
  },
  figure_revised: { name: "Figure revised", does: "An outlet later gave a figure outside the range of its own first report.", params: {} },
  anonymous_sourcing: {
    name: "Anonymous sourcing", does: "Some independent texts name who said a claim and at least one cites only unnamed sources.",
    params: { min_named_origins: "Independent texts that name the speaker", min_anonymous_origins: "Independent texts citing only unnamed sources" },
  },
  single_origin: {
    name: "One speaker behind it", does: "A widely carried claim traces back to one speaker.",
    params: { min_origins: "Independent texts carrying the claim", min_share: "Share that attribute it to one speaker" },
  },
  conflicting_accounts: { name: "Conflicting accounts", does: "Two groups of reports give accounts that cannot both be as written.", params: { min_origins_per_side: "Independent texts on each side" } },
  quote_differs: {
    name: "Quote differs from issued text", does: "A report's quote of a speaker differs from the text that speaker issued.",
    params: { min_edit_ratio: "Smallest share of the text changed", max_edit_ratio: "Largest share changed (beyond this it is a different statement)" },
  },
  silence: {
    name: "Silence", does: "An outlet that usually covers a story has gone quiet while the story's coverage continued.",
    params: { outlet_quiet_hours: "Hours the outlet has been quiet", story_coverage_within: "How far the story's coverage may drift from the prior window", min_prior_reports: "Reports the story needs in the prior window", min_outlet_reports: "Reports the outlet needs in the prior window", skip_unhealthy_feeds: "Skip outlets whose feed is failing" },
  },
  copied_text: {
    name: "Copied text", does: "Several outlets published near-identical text.",
    params: { min_outlets: "Outlets with the same text", min_jaccard: "Smallest text overlap (0 to 1)", shingle_words: "Words per comparison window", window_hours: "Hours within which they were published", require_different_owners: "Outlets must have different owners", ignore_credited_wire_copy: "Ignore copy that credits a wire service" },
  },
  silent_edit: { name: "Silent edit", does: "A report's text changed after publication with no correction note.", params: { refetch_after: "Re-checked after" } },
  loaded_wording: { name: "Loaded wording", does: "An outlet uses a word far more often than other outlets describing the same event.", params: { min_weighted_log_odds: "Smallest difference in how often the word is used", exclude_paywalled_sources: "Leave out paywalled sources" } },
  unattributed: { name: "Unattributed", does: "A claim appears in several versions with no attribution.", params: { min_attributed_versions: "Versions that must attribute it" } },
};

export const ruleName = (id: string): string => RULES[id]?.name ?? id.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
export const RULE_NAMES: Record<string, string> = Object.fromEntries(Object.entries(RULES).map(([k, v]) => [k, v.name]));

const humanValue = (v: unknown): string =>
  typeof v === "boolean" ? (v ? "Yes" : "No") : typeof v === "number" ? nf.format(v) : Array.isArray(v) ? v.join(", ") : String(v);

/** Labelled rows for a rule's thresholds. Unknown keys fall back to readable words, never JSON. */
export function ruleRows(rule: string, values: Record<string, unknown>): [string, string][] {
  const labels = RULES[rule]?.params ?? {};
  return Object.entries(values)
    .filter(([k, v]) => k !== "enabled" && v !== null && (typeof v !== "object" || Array.isArray(v)))
    .map(([k, v]) => [labels[k] ?? k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()), humanValue(v)]);
}

export const KIND_LABEL: Record<string, string> = {
  report_group: "Report group", claim_group: "Claim group", anomaly: "Anomaly", report: "Report", document: "Document",
  statement: "Statement", event: "Event",
};
export const kindLabel = (k: string): string => KIND_LABEL[k] ?? k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

export const STATE_LABEL: Record<string, string> = {
  "state-run": "State-run (cited)", "not state-run": "Not state-run (cited)", unverified: "Ownership unverified",
};
