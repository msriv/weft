# Generic Cloud Run service. Optionally subscribed to a Pub/Sub topic (push, OIDC) and/or public.
variable "project_id" { type = string }
variable "region" { type = string }
variable "name" { type = string }
variable "image" { type = string }
variable "service_account_email" { type = string }
variable "env" {
  type    = map(string)
  default = {}
}
variable "secret_env" {
  description = "Env var name to Secret Manager secret id."
  type        = map(string)
  default     = {}
}
variable "min_instances" {
  type    = number
  default = 0
}
variable "max_instances" {
  type    = number
  default = 3
}
variable "concurrency" {
  type    = number
  default = 20
}
variable "memory" {
  type    = string
  default = "1Gi"
}
variable "cpu" {
  type    = string
  default = "1"
}
variable "push_topic" {
  description = "Pub/Sub topic to push to this service. Empty for none."
  type        = string
  default     = ""
}
variable "extra_pushes" {
  description = "More Pub/Sub topics pushed to a path on this service: name => {topic, path}."
  type        = map(object({ topic = string, path = string }))
  default     = {}
}
variable "public" {
  description = "Allow unauthenticated invocation (the reader-facing API and web app)."
  type        = bool
  default     = false
}

locals {
  pushed = var.push_topic != "" || length(var.extra_pushes) > 0
}

resource "google_project_service" "run" {
  project            = var.project_id
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

resource "google_secret_manager_secret_iam_member" "read" {
  for_each  = var.secret_env
  project   = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.service_account_email}"
}

resource "google_cloud_run_v2_service" "svc" {
  project             = var.project_id
  location            = var.region
  name                = var.name
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account                  = var.service_account_email
    max_instance_request_concurrency = var.concurrency
    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }
    containers {
      image = var.image
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

  depends_on = [google_project_service.run, google_secret_manager_secret_iam_member.read]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  count    = var.public ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.svc.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_service_account" "push" {
  count        = local.pushed ? 1 : 0
  project      = var.project_id
  account_id   = "${var.name}-push"
  display_name = "${var.name} Pub/Sub push"
}

resource "google_cloud_run_v2_service_iam_member" "push" {
  count    = local.pushed ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.svc.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.push[0].email}"
}

resource "google_pubsub_subscription" "push" {
  count                = var.push_topic == "" ? 0 : 1
  project              = var.project_id
  name                 = var.name
  topic                = var.push_topic
  ack_deadline_seconds = 120
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
  push_config {
    push_endpoint = google_cloud_run_v2_service.svc.uri
    oidc_token {
      service_account_email = google_service_account.push[0].email
    }
  }
}

resource "google_pubsub_subscription" "extra" {
  for_each             = var.extra_pushes
  project              = var.project_id
  name                 = "${var.name}-${each.key}"
  topic                = each.value.topic
  ack_deadline_seconds = 120
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
  push_config {
    push_endpoint = "${google_cloud_run_v2_service.svc.uri}${each.value.path}"
    oidc_token {
      service_account_email = google_service_account.push[0].email
    }
  }
}

output "uri" { value = google_cloud_run_v2_service.svc.uri }
