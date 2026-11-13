// Shapes returned by the Weft API (weft_core/readmodel.py). Kept loose where the API is.
export type SourceLabel = {
  id: string; name: string; homepage: string; type: string; country: string | null;
  perspective: string; state_run: "unverified" | "state-run" | "not state-run";
  state_run_source: string | null; owner_id: string | null; ownership_source: string | null;
  paywalled: boolean; healthy: boolean; weight: number | null; weight_insufficient: boolean;
};
export type Issuer = SourceLabel & { is_party: boolean };
export type Party = { party: string; cited: boolean; citation: string | null };
export type StoryCard = {
  id: string; title: string; beat: string; status: "developing" | "quiet"; reports: number;
  events: number; sources: number; perspectives: string[]; anomalies: number;
  provisional_anomalies: number; last_report_at: string | null; parties: Party[];
};
export type Anomaly = {
  id: string; rule: string; rule_version: number; status: "active" | "provisional" | "withdrawn";
  subject_kind: string; subject_id: string; story_id: string | null; event_id: string | null;
  summary: string; inputs: Record<string, unknown>; evidence_ids: string[];
  detail: Record<string, unknown>; since: string;
};
export type GraphNode = {
  id: string; kind: "report_group" | "document"; event_id: string | null; at: string | null;
  anomalies: string[]; perspective?: string; count?: number; sources?: string[];
  report_ids?: string[]; title?: string; doc_kind?: string; issuer?: Issuer | null;
};
export type GraphEdge = {
  kind: "conflict"; event_id: string; groups: string[]; between: string[][]; nli_score: number;
};
export type ShortVersion = {
  reported_by_all: { event_id: string; label: string }[];
  reports_conflict_on: { event_id: string; labels: string[] }[];
  one_perspective_only: { event_id: string; label: string; perspective: string }[];
  no_source_published: string[];
  untracked?: string[];
};
export type StoryGraph = {
  story: StoryCard; as_of: string | null; summary: string[]; perspectives: string[];
  summary_items?: { kind: string; text: string; coverage: string; groups: string[] }[];
  nodes: GraphNode[]; edges: GraphEdge[]; anomalies: Anomaly[];
  events: { id: string; label: string | null; label_source?: string | null; first_seen: string; reports: number; perspectives: string[]; follows?: string | null; thread_id?: string; thread_label?: string | null }[];
  short_version: ShortVersion;
  window: { from: string | null; to: string; days: number; older: boolean };
};
export type ReportView = {
  id: string; url: string; title: string; summary: string; type: string; lang: string | null;
  published_at: string | null; source: SourceLabel; copy_of: string[];
};
export type EventPage = {
  event: { id: string; story_id: string; label: string | null; label_source?: string | null; first_seen: string; reports: number; outlets?: number; origins?: number; perspectives: string[] };
  voices: Record<string, { headline: string | null; headline_source: string | null; words: string[]; reports: number }>;
  perspectives: Record<string, ReportView[]>;
  claim_groups: { id: string; label: string; perspectives: string[]; n_reports: number; claims: { report_id: string; text: string; start: number; end: number }[] }[];
  conflicts: { groups: string[]; nli_score: number }[];
  figures: { id: string; report_id: string; kind: "number" | "quote"; quantity: string | null; value: number | null; unit: string | null; speaker: string | null; text: string }[];
  documents: { id: string; title: string; kind: string; url: string; published_at: string | null; issuer: Issuer | null }[];
  anomalies: Anomaly[];
  short_version: { reported_by_all: string[]; reports_conflict_on: string[][]; one_perspective_only: { group: string; perspective: string }[]; no_source_published: string[]; untracked?: string[] } | null;
  parties: Party[];
};
export type WorldItem = { story_id: string; title: string; country: string; reports: number; perspectives: number; anomalies: number; provisional: boolean; last_report_at: string | null };
export type WorldPlace = WorldItem & { from: Record<string, number> };
export type World = { stories: WorldItem[]; places?: WorldPlace[]; gaps: { story_id: string; title: string; country: string; reports: number }[] };
export type NewEvent = {
  id: string; story_id: string; title: string; beat: string; label: string | null; label_source: string | null;
  first_seen: string; reports: number; outlets: number; perspectives: string[]; new_documents: number;
  follows?: string | null; thread_label?: string | null;
};
export type Today = {
  day: string | null; since: string; changes: { kind: string; label: string; count: number }[];
  new_events: NewEvent[];
  whats_new?: { kind: "new_claim" | "gained_perspective" | "new_conflict"; story_id: string; event_id: string; text: string; perspectives: string[] }[];
  new_anomalies: Anomaly[]; breaking: StoryCard[];
  blind_spots: { story_id: string; title: string; event_id: string; no_source_published: string[]; untracked: string[] }[];
  followed: StoryCard[];
  directions?: string | null;
};

// World directions (D22): model speculation on domains, only with the detective flag on.
export type Speculation = {
  id: string; text: string; probability: number | null; expected_by: string; made_at: string;
  confirm_if: string; refute_if: string; status: "open" | "supported" | "contradicted" | "expired";
  outcome: string; origin: "model" | "template"; kind: "claim" | "numeric"; base_rate: number | null;
  reference_class: string | null; model: string | null; prompt: string | null; evidence: unknown[];
};
export type TrackRecord = {
  resolved: number; counts: Record<string, number>; brier: number | null; brier_half: number;
  brier_base_rate: number | null; base_rate_n: number;
  calibration: { decile: [number, number]; n: number; said: number; happened: number }[];
};
export type Driver = { group_id: string; label: string; event_id: string | null; n_origins: number; perspectives: string[]; outlets: string[] };
export type DomainCard = {
  id: string; label: string; facet: string; subject: string; subject_kind: "country" | "beat"; status: string;
  notice: string; not_advice: string | null;
  direction: { coverage_by_week: number[]; series: { id: string; points: [string, number][]; source: string } | null };
  open: Speculation[]; resolved: Speculation[]; drivers: Driver[]; track_record: TrackRecord;
};
export type Directions = {
  notice: string; disclaimer: string; facets: string[]; domains: DomainCard[];
  calibration: TrackRecord & { by_origin: Record<string, TrackRecord>; by_facet: Record<string, TrackRecord> };
};
