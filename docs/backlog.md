# Backlog

Phase 1 and 2 are broken into tasks. Later phases stay at milestone level until Phase 2's exit check passes. Tick tasks off as they land.

## Before Phase 1: decisions needed from the owner

- [ ] Pick the first beat and its 3–5 languages
- [ ] Pick the GCP region
- [ ] Pick the hosted model provider (OpenAI-compatible API serving Qwen3 and gpt-oss)

## Phase 1: Foundations

Exit: one beat's feeds ingesting reliably for a week.

- [x] Repo skeleton: `weft_core` Python package, `services/`, `pipeline/`, `infra/`, `web/`, `evals/`; uv or pip-tools for deps; ruff + pytest + mypy in CI
- [x] Terraform: `weft-dev` project, GCS buckets (`weft-raw` with 30-day lifecycle, `weft-snapshots`, `weft-models`), BigQuery dataset and tables (`raw_items`, `extracted_items`, `model_calls`, `batch_runs`), Pub/Sub topics, Artifact Registry, service accounts
- [x] Source registry: JSON Schema for `config/sources/*.yaml`, validator in CI, loader in `weft_core`
- [x] Sources come from automated discovery into Turso (D15), not hand seeding; poller and fetcher read the store. Crawler (portals) still reads YAML until portal discovery exists
- [x] `poller` Cloud Run job: RSS/Atom with conditional GET, news sitemaps, per-domain rate limit, robots.txt, publishes `items.new`
- [x] `fetcher` service: fetch, `trafilatura` extract, schema.org metadata, raw to GCS, row to `raw_items`, dedupe by canonical URL + text hash
- [x] Feed health: per-source last success, mark unhealthy, alert
- [x] `crawler` job for portals and transcripts (HTML + PDF, change detection by hash)
- [x] GDELT read: scheduled BigQuery query → `gdelt_candidates`
- [x] Model client in `weft_core`: OpenAI-compatible, pinned model + revision, temperature 0, seed, logs every call to `model_calls`
- [x] Dashboards: items per source per hour, extraction failures

## Phase 2: Nightly graph

Exit: editors rate merge and claim quality on a labelled sample, and it beats the agreed bar.

- [x] Story graph store with `valid_from`/`valid_to` helpers (Turso, D17; replaces Neo4j AuraDB)
- [x] Stream worker stages: type, language ID, MinHash near-dup, entities, embedding, attach-to-event, graph write
- [x] Nightly pipeline skeleton (plain Python, Cloud Run job + Cloud Workflows, D18); each stage re-runs alone
- [x] Re-group stage with LLM merge check on borderline pairs
- [x] Claim extraction with forced JSON schema and source offsets
- [x] Numbers/quotes extraction (regex + dependency parse)
- [x] Claim groups + NLI conflict detection
- [x] Short-version set logic (reported by all / conflict / no source has published)
- [x] Snapshots to GCS + daily diff
- [x] `evals/`: labelled set format, scripts for merges, claims, NLI, translation; eval gate in CI
- [x] Editor review queue (1% sample), API and page in the web app

## Phase 3: Anomalies and core screens
Rules engine with unit tests per rule and suppression case; source weights; API endpoints for story, event, source, document, method; Next.js story view (network + list), event page, source and proceeding pages, How we weigh.

## Phase 4: Private beta
Today, onboarding, follows, email digest, report-a-problem, Weft's corrections log, Firebase auth.

## Phase 5: Live and Ask (v2)
SSE stream to the UI, live view, Ask agent with read-only tools and citation post-check, World desk, person page.

## Phase 6: Scale out
More beats and languages, subscriptions, web push, PWA polish; revisit self-hosted vLLM (decision D7).
