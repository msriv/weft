variable "project_id" { type = string }

resource "google_pubsub_topic" "t" {
  for_each = toset(["items-new", "graph-changed"])
  project  = var.project_id
  name     = each.key
}

output "topic_names" {
  value = { for k, t in google_pubsub_topic.t : k => t.name }
}
