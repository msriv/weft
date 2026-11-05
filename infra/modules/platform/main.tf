variable "project_id" { type = string }
variable "region" { type = string }

resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = "weft"
  format        = "DOCKER"
}

# One service account per service; IAM grants are added with the service that needs them.
resource "google_service_account" "sa" {
  for_each     = toset(["poller", "fetcher", "crawler", "stream-worker", "api"])
  project      = var.project_id
  account_id   = "weft-${each.key}"
  display_name = "Weft ${each.key}"
}
