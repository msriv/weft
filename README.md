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

### First run

- **Time:** the first `--build` downloads the small models (BGE-M3, GlotLID, spaCy, NLI) into the images, several GB and often 10 to 30 minutes; the stream worker then needs a few more minutes to load them before it reports ready. Set `HF_TOKEN` to avoid download rate limits.
- **Required in `.env`:** `MODEL_API_KEY`, `MODEL_NAME` and `MODEL_REVISION` (the example file has working values). Without a key the pipeline still runs but skips every model call; Ask answers 503.
- **Progress:** `docker compose ps` shows readiness (`/readyz`); the admin page (`/admin`) lists pipeline stage runs and sources; `docker compose logs -f poller fetcher stream-worker` shows items moving. The first nightly run starts about 30 minutes after startup. Until stories are published in the admin the public pages show their empty states.

### Seeding and schedules

Seeding is part of startup, through the real pipeline and no hand-seeded sources. `seed` runs the first discovery (reads GDELT, registers real feeds and portals per beat). Then the same jobs production runs, on production's cadence, loop in their own containers: `poller` every 10 min, `discovery` hourly, `crawler` daily, `pipeline` (nightly stages) daily, first run 30 min after start. `fetcher` and `stream-worker` process what the poller publishes.

Detective mode (D20) shows a side panel of clearly labelled speculation on each story page, made during the nightly run and checked against later reports; set `DETECTIVE=off` in `.env` to hide it.

Stories start private. Flip one public with the admin toggle (`Authorization: Bearer $ADMIN_TOKEN` against the API) to see it on the site.

Run a job now: `docker compose run --rm --no-deps --entrypoint "uv run --no-sync python -m pipeline.run" pipeline --stage anomalies`. Reset everything: `docker compose down -v`.

Limits: the emulators are not the real services, so BigQuery and Cloud Tasks behaviour can differ in edge cases. Discovery and polling hit the live internet and obey robots.txt. The graph runs in Neo4j 5 Community (Neo4j Browser at http://localhost:7474, user `neo4j`, password `NEO4J_PASSWORD`); production uses Neo4j AuraDB (D19).
