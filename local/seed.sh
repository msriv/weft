#!/usr/bin/env bash
# Seed the local stack through the real pipeline: discovery -> poller -> crawler -> nightly.
# Needs `docker compose up -d` already running and MODEL_API_KEY in .env.
set -euo pipefail
run() { docker compose --profile jobs run --rm "$@"; }
run discovery   # reads GDELT, registers beats' sources (feeds, portals) in sqld
run poller      # polls feeds, publishes to Pub/Sub; fetcher + stream-worker pick them up
run crawler     # crawls official portals
echo "waiting for fetcher/stream-worker to drain..."; sleep 60
run pipeline    # nightly stages: claims, conflicts, anomalies, snapshot
