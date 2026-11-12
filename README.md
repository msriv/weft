# Weft

A news site that builds a story graph from reports, official documents and public proceedings across every country involved, and flags anomalies where reports don't line up. It never claims what is true.

Start here:

- `CLAUDE.md` — product rules, stack, how to work in this repo
- `docs/spec.md` — technical specification
- `docs/decisions.md` — why things are the way they are
- `docs/backlog.md` — build order and Phase 1–2 tasks
- `docs/design/` — screen designs and tokens
- `config/` — source registry and anomaly rule thresholds

## Run locally (docker compose)

Runs the whole platform on your machine with Neo4j and local stand-ins for GCP: fake-gcs-server (GCS), bigquery-emulator, Pub/Sub emulator, Cloud Tasks emulator, and the Firebase emulators (Auth + Firestore, for reader accounts). No GCP account needed. Needs Docker and an OpenRouter key.

```bash
cp .env.example .env          # set MODEL_API_KEY
docker compose up --build -d  # first build is slow: it downloads the real small models
docker compose logs -f        # watch it work
```

Web: http://localhost:3000. Create a reader account on `/welcome` to try sign-in and synced preferences (Firebase Auth emulator; accounts vanish on `down -v`). API: http://localhost:8080.

### Seeding and schedules

Seeding is part of startup, through the real pipeline and no hand-seeded sources. `seed` runs the first discovery (reads GDELT, registers real feeds and portals per beat). Then the same jobs production runs, on production's cadence, loop in their own containers: `poller` every 10 min, `discovery` hourly, `crawler` daily, `pipeline` (nightly stages) daily, first run 30 min after start. `fetcher` and `stream-worker` process what the poller publishes.

Stories start private. Flip one public with the admin toggle (`Authorization: Bearer $ADMIN_TOKEN` against the API) to see it on the site.

Run a job now: `docker compose run --rm --no-deps --entrypoint "uv run --no-sync python -m pipeline.run" pipeline --stage anomalies`. Reset everything: `docker compose down -v`.

Limits: the emulators are not the real services, so BigQuery and Cloud Tasks behaviour can differ in edge cases. Discovery and polling hit the live internet and obey robots.txt. The graph runs in Neo4j 5 Community (Neo4j Browser at http://localhost:7474, user `neo4j`, password `NEO4J_PASSWORD`); production uses Neo4j AuraDB (D19).
