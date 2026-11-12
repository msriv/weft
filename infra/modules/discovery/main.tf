variable "project_id" { type = string }
variable "region" { type = string }
variable "image" {
  description = "Discovery container image in Artifact Registry. Build and push it before applying with a real value."
  type        = string
}
variable "service_account_email" { type = string }
variable "schedule" {
  description = "Cron for discovery. GDELT publishes every 15 minutes; hourly is plenty for finding new outlets."
  type        = string
  default     = "7 * * * *"
}

# Neo4j AuraDB is managed outside GCP (D19). Terraform creates the secret containers; the values are
# added once with `gcloud secrets versions add` so they never enter Terraform state.
resource "google_project_service" "apis" {
  for_each           = toset(["run.googleapis.com", "cloudscheduler.googleapis.com", "secretmanager.googleapis.com"])
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

resource "google_secret_manager_secret" "neo4j" {
  for_each  = toset(["neo4j-uri", "neo4j-password", "admin-token"])
  project   = var.project_id
  secret_id = "weft-${each.key}"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "read" {
  for_each  = google_secret_manager_secret.neo4j
  project   = var.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.service_account_email}"
}

resource "google_cloud_run_v2_job" "discovery" {
  project             = var.project_id
  location            = var.region
  name                = "weft-discovery"
  deletion_protection = false

  template {
    template {
      service_account = var.service_account_email
      timeout         = "1800s" # polite probing waits 10 s between requests per domain
      max_retries     = 0
      containers {
        image = var.image
        dynamic "env" {
          for_each = { NEO4J_URI = "neo4j-uri", NEO4J_PASSWORD = "neo4j-password" }
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = google_secret_manager_secret.neo4j[env.value].secret_id
                version = "latest"
              }
            }
          }
        }
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.read]
}

resource "google_service_account" "scheduler" {
  project      = var.project_id
  account_id   = "weft-discovery-scheduler"
  display_name = "Weft discovery scheduler"
}

resource "google_cloud_run_v2_job_iam_member" "invoke" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.discovery.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_cloud_scheduler_job" "discovery" {
  project   = var.project_id
  region    = var.region
  name      = "weft-discovery"
  schedule  = var.schedule
  time_zone = "Etc/UTC"

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.discovery.name}:run"
    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  depends_on = [google_project_service.apis]
}

output "neo4j_secret_ids" {
  description = "Secret ids for NEO4J_URI and NEO4J_PASSWORD, for every service that reads the graph."
  value       = { NEO4J_URI = google_secret_manager_secret.neo4j["neo4j-uri"].secret_id, NEO4J_PASSWORD = google_secret_manager_secret.neo4j["neo4j-password"].secret_id }
}

output "admin_token_secret_id" {
  value = google_secret_manager_secret.neo4j["admin-token"].secret_id
}

moved {
  from = google_secret_manager_secret.turso["admin-token"]
  to   = google_secret_manager_secret.neo4j["admin-token"]
}
