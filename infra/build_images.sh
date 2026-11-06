#!/usr/bin/env bash
# Build all images with Cloud Build into Artifact Registry. Usage: infra/build_images.sh <project> <region> [tag]
set -euo pipefail
P=$1 R=$2 TAG=${3:-$(git rev-parse --short HEAD)}
REG=$R-docker.pkg.dev/$P/weft
cd "$(dirname "$0")/.."
build() { # name dockerfile context
  local cfg; cfg=$(mktemp --suffix=.yaml)
  printf 'steps:\n- name: gcr.io/cloud-builders/docker\n  args: [build, -f, %s, -t, %s/%s:%s, .]\nimages: [%s/%s:%s]\n' \
    "$2" "$REG" "$1" "$TAG" "$REG" "$1" "$TAG" > "$cfg"
  gcloud builds submit "$3" --config "$cfg" --project "$P" --region "$R"
  echo "$1_image = \"$REG/$1:$TAG\"" >> images.auto.tfvars
}
: > images.auto.tfvars
for s in poller fetcher crawler discovery stream_worker api; do build "$s" "services/$s/Dockerfile" .; done
build nightly pipeline/Dockerfile .
build web Dockerfile web
mv images.auto.tfvars infra/images.auto.tfvars
