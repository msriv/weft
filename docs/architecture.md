# Architecture

How data moves through the system as built today. The spec (`docs/spec.md`) is the longer description and also lists what is planned; where the two differ, this page matches the code. Decisions are in `docs/decisions.md`.

```mermaid
flowchart TD
  F[News feeds and sitemaps]
  P[poller: Cloud Run job, every 10 min]
  T1{{Pub/Sub items-new}}
  FE[fetcher: Cloud Run service]
  T2{{Pub/Sub items-extracted}}
  SW[stream-worker: Cloud Run service]
  CR[crawler: Cloud Run job, daily]
  T3{{Pub/Sub documents-new}}
  DI[discovery: Cloud Run job, hourly, reads GDELT]
  N[(Neo4j: graph, sources, beats, subscriptions, ledger)]
  GCS[(GCS: raw copies, feed state, snapshots)]
  BQ[(BigQuery: raw_items, extracted_items, source_health, model_calls)]
  WF[Cloud Scheduler to Cloud Workflows]
  NJ[nightly: Cloud Run job, stages in order]
  API[api: Cloud Run service]
  WEB[web: Next.js, proxies /api to the API]
  FS[(Firestore: reader accounts and preferences)]
  F --> P --> T1 --> FE
  P -. feed state .-> GCS
  FE -- raw copy --> GCS
  FE -- log rows --> BQ
  FE -- seen keys --> N
  FE --> T2 --> SW
  CR --> T3 --> SW
  SW -- reports, events, documents --> N
  DI -- sources, candidates --> N
  WF --> NJ
  NJ -- claims, groups, anomalies, short versions --> N
  NJ -- model calls --> BQ
  NJ -. reads text .-> GCS
  N --> API --> WEB
  FS --> API
```

## Steps, and what each reads and writes

| Step | Reads | Writes |
| --- | --- | --- |
| discovery (hourly) | GDELT files, Neo4j (beats, known domains), each candidate's homepage and feeds | `Source` and candidate nodes |
| poller (10 min) | active `Source` nodes, feeds and sitemaps, feed state in GCS | `items-new` messages, feed state, `source_health` rows |
| fetcher | `items-new`, the article URL, `Seen` nodes | raw copy in GCS, `raw_items` and `extracted_items` rows, `Seen` nodes, `items-extracted` |
| stream-worker | `items-extracted`, `documents-new`, beats and open events in Neo4j | `Report`, `Event`, `Story`, `Document`, entity and copy nodes |
| crawler (daily) | portal pages | raw copy, `documents-new` |
| nightly stages | reports, events and raw text, the model | claims, claim groups, conflicts, anomalies (rules engine, no model), short versions, summaries, `BatchRun` nodes, `model_calls` rows |
| api | Neo4j, Firestore | nothing, except subscriptions, reader reports and the admin toggles |
| web | the API | nothing |

## Rules that shape the flow
- Anomalies come from `pipeline/anomalies` and `config/rules.yaml` only. Models supply inputs (claims, groups, entities).
- Every model call goes through `weft_core/models.py` (pinned, logged, capped by the daily ledger).
- A story is private (404) until the admin publishes it.
- Raw copies live 30 days in GCS; Neo4j keeps summaries and links.

## Not built (D24)
Apache Beam on Dataflow and Memorystore Redis. The live story stream polls the graph.
