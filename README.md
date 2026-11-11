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

Runs the whole platform on your machine with local stand-ins for GCP: sqld (Turso), fake-gcs-server (GCS), bigquery-emulator, Pub/Sub emulator and Cloud Tasks emulator. No GCP account needed. Needs Docker and an OpenRouter key.

```bash
cp .env.example .env        # set MODEL_API_KEY
docker compose up --build -d
```

First build is slow: the stream worker and nightly images download the real small models (BGE-M3, GlotLID, spaCy). Web is at http://localhost:3000, API at http://localhost:8080.

### Seed it with the real pipeline

No hand-seeded sources. `local/seed.sh` runs the same jobs production runs:

1. `discovery` reads the newest GDELT file, finds real feeds and portals for each beat, and registers them.
2. `poller` polls those feeds and publishes new items; `fetcher` and `stream-worker` extract, group and attach them to events.
3. `crawler` crawls official portals.
4. `pipeline` runs the nightly stages (claims, conflicts, anomalies, snapshot).

```bash
./local/seed.sh
```

Run one job on its own with `docker compose --profile jobs run --rm poller` (or `discovery`, `crawler`, `pipeline`; `pipeline --stage anomalies` re-runs one stage). Stories start private: flip one public with the admin toggle (`Authorization: Bearer $ADMIN_TOKEN` against the API) to see it on the site.

Reset everything: `docker compose down -v`.

Limits: the emulators are not the real services, so BigQuery and Cloud Tasks behaviour can differ in edge cases. Firestore (accounts) and Neo4j are not used by the current code, so they are not in the stack. Discovery and polling hit the live internet and obey robots.txt.
