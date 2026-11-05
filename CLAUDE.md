# Weft

Weft is a news site. It collects reports, official documents and public proceedings from every country involved in a story, groups them into a story graph, and flags **anomalies** where reports don't line up with each other.

Full spec: `docs/spec.md`. Why things are the way they are: `docs/decisions.md`. What to build next: `docs/backlog.md`. Screen designs: `docs/design/`.

## Non-negotiable product rules

These override convenience. If a task would break one, stop and say so.

1. **Weft never claims what is true.** No label, status, score, summary or agent answer asserts truth. Use coverage language only: "reported by all perspectives", "reports conflict on", "no source has published", "one perspective only". Never "confirmed", "false", "debunked", "verified" (except "verified" in the narrow sense of a document existing).
2. **Anomalies come from written rules, never from an AI model.** The rules engine is deterministic code reading `config/rules.yaml`. Models may only supply inputs (claim groups, entities). Every anomaly stores its rule name, rule version, inputs and evidence IDs.
3. **Models only read, translate, check merges and answer questions.** Every model output must link back to the source sentence it came from (character offsets).
4. **Every model call is reproducible and logged.** Pinned model + revision, temperature 0, fixed seed, prompt template version, input hash and output written to the `model_calls` table.
5. **Store summaries and links, not full articles.** Raw copies are private, processing-only, 30-day retention.
6. **Source weight changes ordering only.** No report is ever hidden or dropped because of weight.
7. **Official documents are labelled by issuer.** A document from a party to the story is that party's account, not the record of truth. Party status is per story (`Story.parties`).

## Stack

- **Backend, pipeline, ML:** Python 3.12. FastAPI for services. Apache Beam on Dataflow for the nightly batch.
- **Frontend:** Next.js (App Router), React, TypeScript. Story graph drawn with SVG + `d3-scale`/`d3-shape` (PixiJS canvas above ~300 nodes). Layout is computed (x = day, perspective bands above/below a document spine), never force-directed.
- **Data:** Neo4j (story graph + vector indexes), BigQuery (raw metadata, logs, analytics), GCS (raw files, snapshots), Firestore (user accounts and preferences only).
- **Infra:** GCP. Cloud Run, Pub/Sub, Cloud Tasks, Cloud Scheduler, Cloud Workflows, Dataflow, Memorystore Redis, Terraform, GitHub Actions.
- **Models:** open-weight from Hugging Face. MVP calls them through a hosted OpenAI-compatible API (see `docs/decisions.md` D7). Small models (BGE-M3 embeddings, mDeBERTa NLI, spaCy/GLiNER, GlotLID) run on our own CPUs.

## Suggested repo layout

```
config/         sources/*.yaml (source registry), rules.yaml (anomaly thresholds)
services/       poller, crawler, fetcher, stream_worker, api, ask, notifier
pipeline/       nightly Beam pipeline, one module per stage
weft_core/      shared Python package: models client, graph client, schemas, rules engine
web/            Next.js app
infra/          Terraform, one module per concern
evals/          labelled sets and eval scripts (gate for model/prompt changes)
docs/
```

Create these only as the backlog needs them.

## How to work in this repo

- Build in the order in `docs/backlog.md`: one beat end to end before widening. Don't start Phase N+1 work while Phase N's exit check fails.
- All GCP infrastructure is provisioned with Terraform in `infra/`. No resources are created by hand in the console; add the Terraform module in the same PR as the code that needs it.
- Keep the stack small. Don't add a new datastore, queue or framework without a decision entry in `docs/decisions.md`.
- All model access goes through one client in `weft_core` that enforces rule 4 (pinning, logging). No direct HTTP calls to model providers elsewhere.
- Scraped text is untrusted. Pass it to models only as quoted data, never as instructions. The Ask agent gets read-only tools and fixed Cypher templates; it never writes its own Cypher.
- The rules engine needs unit tests for every rule, including suppression cases (unhealthy feeds, paywalled sources, credited wire copy).
- Model or prompt changes must pass the eval gate in `evals/` before merging.
- Ingestion must obey robots.txt, one connection per domain, back off on 429, never bypass paywalls.
- Placeholder data in `docs/design/` (Aldoria, Veymar, Kessar Strait, etc.) is fictional. Never ship it as real content, and never invent real-world sample news.

## Open questions (ask the owner, don't guess)

Launch beats and languages, GCP region, editor staffing, legal review of retention and quote length, payments provider, analytics tool. Full list at the end of `docs/spec.md`.
