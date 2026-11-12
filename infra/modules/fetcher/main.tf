variable "project_id" { type = string }
variable "region" { type = string }
variable "image" {
  description = "Fetcher container image in Artifact Registry."
  type        = string
}
variable "service_account_email" { type = string }
variable "raw_bucket" { type = string }
variable "dataset_id" { type = string }
variable "items_new_topic" { type = string }

resource "google_project_service" "run" {
  project            = var.project_id
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

resource "google_storage_bucket_iam_member" "raw_write" {
  bucket = var.raw_bucket
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${var.service_account_email}"
}

resource "google_bigquery_dataset_iam_member" "edit" {
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

# One instance and one request at a time: the fetcher keeps one connection per domain.
resource "google_cloud_run_v2_service" "fetcher" {
  project             = var.project_id
  location            = var.region
  name                = "weft-fetcher"
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account                  = var.service_account_email
    max_instance_request_concurrency = 1
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    containers {
      image = var.image
      env {
        name  = "PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "RAW_BUCKET"
        value = var.raw_bucket
      }
      env {
        name  = "REGION"
        value = var.region
      }
      env {
        name  = "REFETCH_QUEUE"
        value = google_cloud_tasks_queue.refetch.name
      }
      env {
        name  = "TASKS_SERVICE_ACCOUNT"
        value = var.service_account_email
      }
      dynamic "env" {
        for_each = var.neo4j_secret_ids
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

  depends_on = [google_project_service.run]
}

resource "google_service_account" "push" {
  project      = var.project_id
  account_id   = "weft-fetcher-push"
  display_name = "Weft fetcher Pub/Sub push"
}

resource "google_cloud_run_v2_service_iam_member" "invoke" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.fetcher.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.push.email}"
}

resource "google_pubsub_subscription" "fetcher" {
  project = var.project_id
  name    = "fetcher"
  topic   = var.items_new_topic

  ack_deadline_seconds = 120
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  push_config {
    push_endpoint = google_cloud_run_v2_service.fetcher.uri
    oidc_token {
      service_account_email = google_service_account.push.email
    }
  }
}

variable "neo4j_secret_ids" {
  description = "Env var name to Secret Manager secret id for the Neo4j connection."
  type        = map(string)
}

resource "google_secret_manager_secret_iam_member" "neo4j" {
  for_each  = var.neo4j_secret_ids
  project   = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.service_account_email}"
}

# Re-fetches at +1 h, +24 h and +7 days for the silent-edit rule. Tasks call POST /refetch on the
# fetcher as its own service account, so it needs the invoker role on itself.
resource "google_project_service" "tasks" {
  project            = var.project_id
  service            = "cloudtasks.googleapis.com"
  disable_on_destroy = false
}

resource "google_cloud_tasks_queue" "refetch" {
  project  = var.project_id
  location = var.region
  name     = "weft-refetch"
  rate_limits {
    max_dispatches_per_second = 1
  }
  retry_config {
    max_attempts = 5
    min_backoff  = "60s"
  }
  depends_on = [google_project_service.tasks]
}

resource "google_project_iam_member" "enqueue" {
  project = var.project_id
  role    = "roles/cloudtasks.enqueuer"
  member  = "serviceAccount:${var.service_account_email}"
}

resource "google_service_account_iam_member" "act_as_self" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/${var.service_account_email}"
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.service_account_email}"
}

resource "google_cloud_run_v2_service_iam_member" "invoke_self" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.fetcher.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.service_account_email}"
}

resource "google_storage_bucket_iam_member" "raw_read" {
  bucket = var.raw_bucket
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${var.service_account_email}"
}
