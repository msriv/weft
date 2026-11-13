import countries from "i18n-iso-countries";
import en from "i18n-iso-countries/langs/en.json";

countries.registerLocale(en);

/** Perspective code (usually an ISO 3166 country) to a readable name. */
export function perspectiveName(code: string): string {
  if (code === "unattributed") return "Country not known";
  return countries.getName(code, "en") ?? code;
}

export function day(iso: string | null): string {
  return iso ? iso.slice(0, 10) : "";
}

export function ago(iso: string | null, now = Date.now()): string {
  if (!iso) return "";
  const m = Math.round((now - Date.parse(iso)) / 60000);
  if (m < 60) return `${Math.max(m, 0)} min ago`;
  if (m < 60 * 48) return `${Math.round(m / 60)} h ago`;
  return `${Math.round(m / 1440)} days ago`;
}

export const RULE_NAMES: Record<string, string> = {
  omission: "Omission", numbers_differ: "Numbers differ", silence: "Silence",
  copied_text: "Copied text", silent_edit: "Silent edit", loaded_wording: "Loaded wording",
  unattributed: "Unattributed", figure_revised: "Figure revised", anonymous_sourcing: "Anonymous sourcing",
  single_origin: "One speaker behind it", conflicting_accounts: "Conflicting accounts", quote_differs: "Quote differs from issued text",
};

export const STATE_LABEL: Record<string, string> = {
  "state-run": "State-run (cited)", "not state-run": "Not state-run (cited)", unverified: "Ownership unverified",
};
