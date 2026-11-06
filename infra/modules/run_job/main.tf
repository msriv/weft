# Generic Cloud Run job, optionally on a Cloud Scheduler cron.
variable "project_id" { type = string }
variable "region" { type = string }
variable "name" { type = string }
variable "image" { type = string }
variable "service_account_email" { type = string }
variable "command" {
  description = "Container args, e.g. [\"python\", \"-m\", \"pipeline.run\"]. Empty uses the image CMD."
  type        = list(string)
  default     = []
}
variable "env" {
  type    = map(string)
  default = {}
}
variable "secret_env" {
  type    = map(string)
  default = {}
}
variable "timeout" {
  type    = string
  default = "3600s"
}
variable "cpu" {
  type    = string
  default = "2"
}
variable "memory" {
  type    = string
  default = "4Gi"
}
variable "schedule" {
  description = "Cron (UTC). Empty means no scheduler; something else (Workflows) starts the job."
  type        = string
  default     = ""
}

resource "google_project_service" "apis" {
  for_each           = toset(["run.googleapis.com", "cloudscheduler.googleapis.com"])
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

resource "google_secret_manager_secret_iam_member" "read" {
  for_each  = var.secret_env
  project   = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.service_account_email}"
}

resource "google_cloud_run_v2_job" "job" {
  project             = var.project_id
  location            = var.region
  name                = var.name
  deletion_protection = false

  template {
    template {
      service_account = var.service_account_email
      timeout         = var.timeout
      max_retries     = 0
      containers {
        image = var.image
        args  = length(var.command) == 0 ? null : var.command
        resources {
          limits = { cpu = var.cpu, memory = var.memory }
        }
        dynamic "env" {
          for_each = var.env
          content {
            name  = env.key
            value = env.value
          }
        }
        dynamic "env" {
          for_each = var.secret_env
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

  depends_on = [google_project_service.apis, google_secret_manager_secret_iam_member.read]
}

resource "google_service_account" "scheduler" {
  count        = var.schedule == "" ? 0 : 1
  project      = var.project_id
  account_id   = "${var.name}-sched"
  display_name = "${var.name} scheduler"
}

resource "google_cloud_run_v2_job_iam_member" "invoke" {
  count    = var.schedule == "" ? 0 : 1
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.job.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler[0].email}"
}

resource "google_cloud_scheduler_job" "job" {
  count     = var.schedule == "" ? 0 : 1
  project   = var.project_id
  region    = var.region
  name      = var.name
  schedule  = var.schedule
  time_zone = "Etc/UTC"
  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.job.name}:run"
    oauth_token {
      service_account_email = google_service_account.scheduler[0].email
    }
  }
  depends_on = [google_project_service.apis]
}

output "name" { value = google_cloud_run_v2_job.job.name }
