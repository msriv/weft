# Backlog

Phase 1 and 2 are broken into tasks. Later phases stay at milestone level until Phase 2's exit check passes. Tick tasks off as they land.

## Before Phase 1: decisions needed from the owner

- [ ] Pick the first beat and its 3–5 languages
- [ ] Pick the GCP region
- [ ] Pick the hosted model provider (OpenAI-compatible API serving Qwen3 and gpt-oss)

## Phase 1: Foundations

Exit: one beat's feeds ingesting reliably for a week.

- [ ] Repo skeleton: `weft_core` Python package, `services/`, `pipeline/`, `infra/`, `web/`, `evals/`; uv or pip-tools for deps; ruff + pytest + mypy in CI
- [ ] Terraform: `weft-dev` project, GCS buckets (`weft-raw` with 30-day lifecycle, `weft-snapshots`, `weft-models`), BigQuery dataset and tables (`raw_items`, `extracted_items`, `model_calls`, `batch_runs`), Pub/Sub topics, Artifact Registry, service accounts
- [ ] Source registry: JSON Schema for `config/sources/*.yaml`, validator in CI, loader in `weft_core`
- [ ] Seed 20–40 sources for the first beat across its perspectives, plus its government and parliament portals
- [ ] `poller` Cloud Run job: RSS/Atom with conditional GET, news sitemaps, per-domain rate limit, robots.txt, publishes `items.new`
- [ ] `fetcher` service: fetch, `trafilatura` extract, schema.org metadata, raw to GCS, row to `raw_items`, dedupe by canonical URL + text hash
- [ ] Feed health: per-source last success, mark unhealthy, alert
- [ ] `crawler` job for portals and transcripts (HTML + PDF, change detection by hash)
- [ ] GDELT read: scheduled BigQuery query → `gdelt_candidates`
- [ ] Model client in `weft_core`: OpenAI-compatible, pinned model + revision, temperature 0, seed, logs every call to `model_calls`
- [ ] Dashboards: items per source per hour, extraction failures

## Phase 2: Nightly graph

Exit: editors rate merge and claim quality on a labelled sample, and it beats the agreed bar.

- [ ] Neo4j AuraDB instance, schema constraints, vector indexes, `valid_from`/`valid_to` helpers
- [ ] Stream worker stages: type classification, GlotLID, MinHash near-dup, entities, BGE-M3 embedding, attach-to-event, Neo4j write
- [ ] Nightly pipeline skeleton on Dataflow + Cloud Workflows; each stage reads/writes its own table and can re-run alone
- [ ] Re-group stage with LLM merge check on borderline pairs
- [ ] Claim extraction with forced JSON schema and source offsets
- [ ] Numbers/quotes extraction (regex + dependency parse)
- [ ] Claim groups + NLI conflict detection
- [ ] Short-version set logic (reported by all / conflict / no source has published)
- [ ] Snapshots to GCS + daily diff
- [ ] `evals/`: labelled set format, scripts for merges, claims, NLI, translation; eval gate in CI
- [ ] Editor review queue (1% sample) — simple internal page is fine

## Phase 3: Anomalies and core screens
Rules engine with unit tests per rule and suppression case; source weights; API endpoints for story, event, source, document, method; Next.js story view (network + list), event page, source and proceeding pages, How we weigh.

## Phase 4: Private beta
Today, onboarding, follows, email digest, report-a-problem, Weft's corrections log, Firebase auth.

## Phase 5: Live and Ask (v2)
SSE stream to the UI, live view, Ask agent with read-only tools and citation post-check, World desk, person page.

## Phase 6: Scale out
More beats and languages, subscriptions, web push, PWA polish; revisit self-hosted vLLM (decision D7).
