variable "project_id" { type = string }
variable "region" { type = string }
variable "image" {
  description = "Poller container image in Artifact Registry. Build and push it before applying with a real value."
  type        = string
}
variable "service_account_email" { type = string }
variable "state_bucket" { type = string }
variable "dataset_id" { type = string }
variable "items_new_topic" { type = string }
variable "schedule" {
  description = "Cron for the poll run. Spec cadence for news feeds is every 5-15 minutes."
  type        = string
  default     = "*/10 * * * *"
}

resource "google_project_service" "apis" {
  for_each           = toset(["run.googleapis.com", "cloudscheduler.googleapis.com"])
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

resource "google_pubsub_topic_iam_member" "publish" {
  project = var.project_id
  topic   = var.items_new_topic
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${var.service_account_email}"
}

resource "google_storage_bucket_iam_member" "state" {
  bucket = var.state_bucket
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.service_account_email}"
}

resource "google_cloud_run_v2_job" "poller" {
  project             = var.project_id
  location            = var.region
  name                = "weft-poller"
  deletion_protection = false

  template {
    template {
      service_account = var.service_account_email
      timeout         = "600s"
      max_retries     = 0
      containers {
        image = var.image
        env {
          name  = "PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "STATE_BUCKET"
          value = var.state_bucket
        }
        dynamic "env" {
          for_each = var.turso_secret_ids
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = env.value
                version = "latest"
              }
            }
          }
        }
      }
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_service_account" "scheduler" {
  project      = var.project_id
  account_id   = "weft-poller-scheduler"
  display_name = "Weft poller scheduler"
}

resource "google_cloud_run_v2_job_iam_member" "invoke" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.poller.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_cloud_scheduler_job" "poller" {
  project   = var.project_id
  region    = var.region
  name      = "weft-poller"
  schedule  = var.schedule
  time_zone = "Etc/UTC"

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.poller.name}:run"
    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  depends_on = [google_project_service.apis]
}

# Feed health: the poller appends to source_health and reads last success per source.
resource "google_bigquery_dataset_iam_member" "health" {
  project    = var.project_id
  dataset_id = var.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${var.service_account_email}"
}

resource "google_project_iam_member" "bq_jobs" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${var.service_account_email}"
}

variable "turso_secret_ids" {
  description = "Env var name to Secret Manager secret id for the Turso source store."
  type        = map(string)
}

resource "google_secret_manager_secret_iam_member" "turso" {
  for_each  = var.turso_secret_ids
  project   = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.service_account_email}"
}
