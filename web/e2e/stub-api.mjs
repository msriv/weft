// Stub of the Weft API for screenshots and the browser smoke test. Every place, outlet and
// number here is fictional (Aldoria, Veymar, Kessar Strait). Run: node e2e/stub-api.mjs [port]
import { createServer } from "node:http";

const src = (id, name, country, perspective, extra = {}) => ({
  id, name, homepage: `https://${id}.example`, type: "newspaper", country, perspective, state_run: "not state-run",
  state_run_source: null, owner_id: null, ownership_source: null, paywalled: false, healthy: true, weight: 0.6, weight_insufficient: false, ...extra,
});
const S = {
  post: src("aldoria-post", "The Aldoria Post", "AL", "AL"),
  wire: src("veymar-wire", "Veymar Wire", "VE", "VE"),
  rev: src("kessar-review", "Kessar Review", "KE", "KE"),
};
const STORY = {
  id: "kessar-strait", title: "Vessels detained in the Kessar Strait", beat: "kessar", beat_name: "Kessar Strait", status: "developing", reports: 14, events: 3, sources: 3,
  perspectives: ["AL", "VE", "KE"], anomalies: 1, provisional_anomalies: 1, last_report_at: "2026-11-14T09:30:00Z",
  parties: [{ party: "AL", cited: true, citation: "Ministry of Maritime Affairs" }, { party: "VE", cited: false, citation: null }],
};
const iso = (d) => `2026-11-${String(d).padStart(2, "0")}T08:00:00Z`;
const nodes = [
  { id: "n1", kind: "report_group", event_id: "e1", at: iso(10), anomalies: [], perspective: "AL", count: 4, sources: ["The Aldoria Post"], report_ids: ["r1"] },
  { id: "n2", kind: "report_group", event_id: "e1", at: iso(10), anomalies: ["a1"], perspective: "VE", count: 3, sources: ["Veymar Wire"], report_ids: ["r2"] },
  { id: "n3", kind: "report_group", event_id: "e2", at: iso(12), anomalies: [], perspective: "KE", count: 2, sources: ["Kessar Review"], report_ids: ["r3"] },
  { id: "n4", kind: "report_group", event_id: "e2", at: iso(12), anomalies: [], perspective: "AL", count: 5, sources: ["The Aldoria Post"], report_ids: ["r4"] },
  { id: "n5", kind: "document", event_id: "e1", at: iso(11), anomalies: [], title: "Statement on the detentions", doc_kind: "statement", issuer: { ...src("min-maritime", "Ministry of Maritime Affairs", "AL", "AL"), is_party: true } },
];
const anomaly = { id: "a1", rule: "numbers_differ", rule_version: 1, status: "provisional", subject_kind: "event", subject_id: "e1", story_id: "kessar-strait", event_id: "e1",
  summary: "Reports differ on the number of vessels detained: 12 in The Aldoria Post, 9 in Veymar Wire.", inputs: { a: 12, b: 9 }, evidence_ids: ["r1", "r2"], detail: { figures: [{ id: "f1", text: "12 vessels", value: 12 }, { id: "f2", text: "9 vessels", value: 9 }] }, since: iso(13),
  evidence: [{ id: "r1", outlet: "The Aldoria Post", perspective: "AL", published_at: iso(11) }, { id: "r2", outlet: "Veymar Wire", perspective: "VE", published_at: iso(10) }],
  provisional_reason: "Only 2 perspectives have reported so far; needs 3." };
const graph = {
  story: STORY, as_of: null, summary: [], perspectives: ["AL", "VE", "KE"], nodes, anomalies: [anomaly],
  edges: [{ kind: "conflict", event_id: "e1", groups: ["g1", "g2"], between: [["AL"], ["VE"]], nli_score: 0.91 }],
  events: [
    { id: "e1", label: "Vessels detained near the strait", first_seen: iso(10), reports: 7, perspectives: ["AL", "VE"] },
    { id: "e2", label: "Talks announced", first_seen: iso(12), reports: 7, perspectives: ["KE", "AL"] },
    { id: "e3", label: "Ports reopen", first_seen: iso(14), reports: 0, perspectives: [] },
  ],
  short_version: {
    reported_by_all: [{ event_id: "e2", label: "Talks were announced for next week" }],
    reports_conflict_on: [{ event_id: "e1", labels: ["Twelve vessels were detained", "Nine vessels were detained"] }],
    one_perspective_only: [{ event_id: "e2", label: "Fuel prices rose at Port Ostia", perspective: "KE" }],
    no_source_published: ["VE"],
  },
  window: { from: null, to: iso(14), days: 7, older: false },
};
const rep = (id, title, source) => ({ id, url: `https://${source.id}.example/${id}`, title, summary: `${title}.`, type: "news", lang: "en", published_at: iso(10), source, copy_of: [] });
const event = {
  event: { id: "e1", story_id: "kessar-strait", label: "Vessels detained near the strait", first_seen: iso(10), reports: 7, outlets: 2, origins: 2, perspectives: ["AL", "VE"] },
  voices: { AL: { headline: "Twelve vessels detained", headline_source: "The Aldoria Post", words: ["detained", "twelve"], reports: 4 }, VE: { headline: "Nine vessels held", headline_source: "Veymar Wire", words: ["held", "nine"], reports: 3 } },
  perspectives: { AL: [rep("r1", "Twelve vessels detained in the strait", S.post)], VE: [rep("r2", "Nine vessels held at Veymar port", S.wire)] },
  claim_groups: [
    { id: "g1", label: "Twelve vessels were detained", perspectives: ["AL"], n_reports: 4, claims: [{ report_id: "r1", text: "Twelve vessels were detained.", start: 0, end: 28 }] },
    { id: "g2", label: "Nine vessels were detained", perspectives: ["VE"], n_reports: 3, claims: [{ report_id: "r2", text: "Nine vessels were held.", start: 0, end: 23 }] },
  ],
  conflicts: [{ groups: ["g1", "g2"], nli_score: 0.91 }],
  figures: [
    { id: "f1", report_id: "r1", kind: "number", quantity: "vessels detained", value: 12, unit: "vessels", speaker: null, text: "Twelve vessels" },
    { id: "f2", report_id: "r2", kind: "number", quantity: "vessels detained", value: 9, unit: "vessels", speaker: null, text: "Nine vessels" },
    { id: "f3", report_id: "r1", kind: "quote", quantity: null, value: null, unit: null, speaker: "Minister Oren Vael", text: "We acted within our waters." },
  ],
  documents: [], anomalies: [anomaly], short_version: null, parties: STORY.parties,
};
const routes = {
  "/v1/world": { stories: [{ story_id: "kessar-strait", title: STORY.title, country: "AL", reports: 14, perspectives: 3, anomalies: 1, provisional: true, last_report_at: STORY.last_report_at }], gaps: [{ story_id: "kessar-strait", title: STORY.title, country: "VE", reports: 0 }] },
  "/v1/stories": [STORY],
  "/v1/stories/kessar-strait": graph,
  "/v1/events/e1": event,
  "/v1/today": { day: "2026-11-14", since: iso(13), changes: [], new_events: [{ id: "e2", story_id: "kessar-strait", title: STORY.title, beat: "kessar", label: "Talks announced", label_source: null, first_seen: iso(12), reports: 7, outlets: 2, perspectives: ["KE", "AL"], new_documents: 0 }], new_anomalies: [anomaly], breaking: [STORY], blind_spots: [], followed: [] },
  "/v1/sources": [S.post, S.wire, S.rev],
};
// A busy story: 70 groups, 5 perspectives, 7 days, for layout checks.
const P5 = ["AL", "VE", "KE", "OR", "TA"];
const busyNodes = Array.from({ length: 70 }, (_, i) => ({
  id: `b${i}`, kind: "report_group", event_id: `e${i % 6}`, at: `2026-11-${String(8 + ((i * 3) % 7)).padStart(2, "0")}T0${i % 9}:00:00Z`,
  anomalies: i === 4 ? ["a1"] : [], perspective: P5[(i * 7) % 5], count: 1 + ((i * 13) % 40), sources: ["The Aldoria Post"], report_ids: [],
}));
routes["/v1/stories/busy"] = { ...graph, story: { ...STORY, id: "busy", title: "A busy story", perspectives: P5 }, perspectives: P5, nodes: busyNodes, edges: [],
  events: Array.from({ length: 6 }, (_, i) => ({ id: `e${i}`, label: `Event ${i + 1} of the busy story`, first_seen: iso(8 + i), reports: 10, perspectives: P5 })) };
const port = Number(process.argv[2] ?? 8080);
createServer((req, res) => {
  const path = new URL(req.url, "http://x").pathname;
  const body = routes[path.replace(/\?.*/, "")] ?? (path === "/v1/directions" ? { domains: [], facets: [], notice: "", disclaimer: "", calibration: {} } : null);
  res.writeHead(body ? 200 : 404, { "content-type": "application/json" });
  res.end(JSON.stringify(body ?? { detail: "not found" }));
}).listen(port, () => console.log(`stub api on ${port}`));
