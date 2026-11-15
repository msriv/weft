# Dead-letter topic for one push subscription (#150): a message that fails max_delivery_attempts
# times lands here instead of vanishing after the 7-day retention. A pull subscription keeps it
# for 14 days so someone can look at it, and the monitoring module alerts on its backlog.
variable "project_id" { type = string }
variable "name" {
  description = "Name of the push subscription this belongs to."
  type        = string
}

data "google_project" "p" {
  project_id = var.project_id
}

resource "google_pubsub_topic" "dead" {
  project = var.project_id
  name    = "${var.name}-dead"
}

resource "google_pubsub_subscription" "pull" {
  project                    = var.project_id
  name                       = "${var.name}-dead-pull" # the alert matches on this suffix
  topic                      = google_pubsub_topic.dead.id
  ack_deadline_seconds       = 60
  message_retention_duration = "1209600s" # 14 days
}

# Pub/Sub's own service account republishes to the dead-letter topic.
resource "google_pubsub_topic_iam_member" "agent_publish" {
  project = var.project_id
  topic   = google_pubsub_topic.dead.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:service-${data.google_project.p.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

output "topic_id" { value = google_pubsub_topic.dead.id }
