# Decisions

Short record of what was decided and why. Add an entry before changing any of these.

## D1. Weft reports coverage, never truth
**Decided:** No label, score or answer says what is true. Labels describe coverage ("reported by all perspectives", "reports conflict on", "no source has published").
**Why:** A site that rules on truth becomes a participant in the fight it's trying to referee, and both sides will attack its verdicts. Reporting who said what is defensible.
**Consequence:** No "confirmed/contradicted" statuses. Source weights never use "was this outlet right".

## D2. Anomalies are rule-based, not AI
**Decided:** Seven deterministic rules (omission, numbers differ, silence, copied text, loaded wording, unattributed, silent edit) with thresholds in `config/rules.yaml`.
**Why:** Answers the "AI is biased" objection. Every flag can be explained and reproduced. Reduces defamation risk.

## D3. Official documents are not "the record of truth"
**Decided:** Documents are labelled by issuer and whether the issuer is a party to the story (per-story `parties` list).
**Why:** A defence ministry's report on its own conflict is that side's account.

## D4. Open-weight models, narrow roles
**Decided:** Models only extract claims, check merges, translate, and answer questions (Ask agent, digests). Never flag anomalies or score sources.
**Why:** Keeps outputs traceable to source sentences, and the "we run open models you can audit" story helps with AI pushback.

## D5. Mostly pipeline steps, only two agents
**Decided:** Claim extraction and merge checks are single structured calls. Only the Ask agent and the digest writer are agentic loops.
**Why:** Agents everywhere would cost more, give non-reproducible results, and make anomalies unexplainable.

## D6. One graph store: Neo4j with its built-in vector index
**Decided:** Neo4j (AuraDB) for graph + vectors. BigQuery for raw/logs/analytics. No separate vector DB.
**Why:** Fewer systems, nothing to keep in sync.

## D7. Hosted API first, self-host later
**Decided:** MVP calls the open-weight models (Qwen3-14B, Qwen3-8B, gpt-oss-20b) through a hosted OpenAI-compatible API. Small CPU models (BGE-M3, NLI, spaCy/GLiNER, GlotLID) run on our own Cloud Run.
**Why:** At MVP volume (est. ~360M input / ~51M output tokens a month), hosted open-weight models cost roughly $11–50/month vs ~$620/month for self-hosted L4 GPUs. Closed cheap tiers (Claude Haiku 5.5, GPT-6 Luna) are ~$60/month, but can't be pinned and get retired. Same models + same API shape means moving to self-hosted vLLM later is an endpoint change.
**Watch:** Hosted providers can change quantization silently. Log provider + model + date on every call; re-run evals if outputs drift. Revisit self-hosting when the monthly API bill clearly exceeds the cost of busy GPUs.
**Prices:** third-party figures as of Nov 2, 2026; re-check before budgeting.

## D8. Daily batch plus real-time ingest
**Decided:** Stream path attaches items within minutes (provisional). Nightly batch re-groups, extracts claims and computes anomalies and weights.
**Why:** Daily-only would leave breaking stories a day stale; real-time-only accumulates grouping errors.

## D9. Anomalies are provisional early
**Decided:** Provisional until ≥ 5 sources from ≥ 2 perspectives and 6 hours since first report. No notifications for provisional anomalies.
**Why:** First-hour coverage is thin; gaps then aren't omissions.

## D10. Live view is opt-in
**Decided:** Digest is the default. Live view is turned on per story. Notifications only for new documents and non-provisional anomalies.
**Why:** A ticking feed recreates the doomscrolling pattern Weft exists to counter.

## D11. GDELT is a discovery feed, not a source of record
**Decided:** Use GDELT to find new outlets, measure coverage gaps, and as a weak grouping signal. Never show its tone scores or event codes.
**Why:** Free, global, 15-minute, BigQuery-native; but machine-coded and noisy. Note FIPS 10-4 country codes.

## D12. Summaries, not articles
**Decided:** Store and show summaries, short quotes and links. Raw copies private, 30-day retention (pending legal review).

## D13. No ads
**Decided:** Funded by reader subscriptions and donations (exact model open). No advertising, no funding from parties covered.

## D14. Name: Weft
**Decided:** "Weft". In weaving, the warp is the fixed threads and the weft is woven across them: the record is the warp, narratives are the weft. Alternatives considered: Parallax, Sightline, Undercurrent. Trademark and domain not yet checked.

## D15. Automation first: sources and stories are created by the pipeline, an admin toggle publishes
**Decided (Mihir, 2026-11-06):** Weft runs without manual steps. Sources, stories and their parties are created by the pipeline and stored in the operational database, not hand-written in git. Nothing is public until an admin turns on a per-story visibility toggle.
**What changes:** The git-reviewed `config/sources/*.yaml` registry (spec, Source registry) becomes a seed and export format, not the source of truth. Source discovery (GDELT candidates grouped by domain per story, feeds found automatically) writes records directly. The 1% review sample stays optional, not a gate.
**What does not change:** The product rules. Ownership and `state_run` facts still carry a citation, or are stored as "unverified" and shown that way. Party status stays per story (rule 7), proposed by the pipeline and editable by an admin. Source weight changes ordering only (rule 6). Visibility is the only human gate.
**Why:** The system is meant to scale to many stories and languages without staffing a review queue for every source.

## D16. Operational database: Turso
**Status:** Superseded by D19. Cloud SQL was never part of the plan and is too costly for now.
**Idea:** Turso (libSQL) holds operational data: sources, stories, parties, feed health, admin toggles. Neo4j AuraDB keeps the story graph and vectors (D6) unless a comparison shows Turso can carry those too.
**Open:** Neo4j AuraDB vs Turso for the graph (cost, graph queries, vector search, operations). Needs a decision entry before any Turso code, per CLAUDE.md.

## D17. Story graph on Turso, not Neo4j (supersedes D6 for the MVP)
**Status:** Reversed by D19.
**Was decided (default, reversible):** The story graph lives in Turso (libSQL) as relational tables that mirror the node and relationship names in the spec (`reports`, `events`, `claims`, `claim_groups`, `anomalies`, ...). Every row carries `valid_from` and `valid_to`; nothing is deleted. Vectors are stored as JSON arrays and searched in Python over the open events of the last 72 hours.
**Why:** Mihir asked for Turso over a paid graph database to keep cost down. At MVP volume (four beats, English) a stream attach looks at tens of events and the nightly job at a few thousand reports, so graph traversals are two-hop joins and brute-force cosine is fast enough. One datastore instead of two.
**Cost of this choice:** No native graph queries and no ANN index. The Ask agent's "fixed Cypher templates" become fixed SQL templates with the same rule: the agent never writes its own query. If volume outgrows this, move the `graph.py` accessors to Neo4j AuraDB or use libSQL native vector columns; callers go through `weft_core.graph`, so only that module changes.
**Does not change:** Rules 1 to 7, the node and relationship model, and `valid_from`/`valid_to` on everything.

## D18. Nightly stages are plain Python run as a Cloud Run job
**Decided (default, reversible):** Each nightly stage is a function in `pipeline/` that reads and writes its own tables and can re-run alone. One Cloud Run job runs them in order, orchestrated by Cloud Workflows, triggered by Cloud Scheduler. Stages are written as pure functions over rows so they can be wrapped in Apache Beam `DoFn`s later without changes.
**Why:** The nightly input is a few thousand reports; Dataflow's per-job startup and cost buy nothing at that size. The 4-hour window is far from tight.
**Revisit when:** a stage exceeds its time budget, or the beat count grows enough that one job instance cannot hold a night's reports in memory.

## D19. No relational database: Neo4j holds the graph and the app's own data (reverses D16, D17)
**Decided (Mihir, 2026-11-12):** Turso is removed. The stack is the one in the spec and `docs/design/Pipeline.dc.html`: Neo4j for the story graph, BigQuery for raw metadata, logs and analytics, GCS for raw files and snapshots, Firestore for reader accounts and preferences.
**Where things live:**
- Neo4j: the story graph (`Report`, `Event`, `Claim`, `ClaimGroup`, `Conflict`, `Figure`, `ShortVersion`, `Anomaly`, `Document`, `Actor`, `Statement`), and the operational records the pipeline and admin need next to it (`Beat`, `Source`, `Story`, `StoryParty`, `SourceWeight`, `ReportVersion`, `Copy`, `ReportEntity`, `PortalCandidate`, `Translation`, `ReviewItem`, `ReaderReport`, `Correction`, `Subscription`, `DailyDiff`, `BatchRun`, `AnomalyLog`). The spec already puts `Source` nodes in Neo4j.
- Firestore: signed-in readers' preferences (`users/{uid}`).
- BigQuery: `raw_items`, `extracted_items`, `model_calls`, `source_health`, `model_evals`.
- GCS: raw copies (30-day), snapshots.
**How:** One Cypher client in `weft_core/store.py`; every node type and its properties are declared in `store.NODES`. `valid_from`/`valid_to` versioning is unchanged: each version is its own node. Local and CI run Neo4j 5 Community; production runs Neo4j AuraDB (credentials in Secret Manager: `weft-neo4j-uri`, `weft-neo4j-password`).
**Shortcut:** nodes join on id properties (indexed) and vectors are still searched in Python; relationships and the Neo4j vector index come when graph size makes that slow. Callers go through `weft_core.graph` and `weft_core.store`, so only those change.

