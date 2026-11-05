variable "project_id" { type = string }
variable "region" { type = string }
variable "raw_retention_days" { type = number }

locals {
  buckets = ["weft-raw", "weft-snapshots", "weft-models"]
}

resource "google_storage_bucket" "b" {
  for_each                    = toset(local.buckets)
  name                        = "${var.project_id}-${each.key}"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  dynamic "lifecycle_rule" {
    for_each = each.key == "weft-raw" ? [1] : []
    content {
      condition {
        age = var.raw_retention_days
      }
      action {
        type = "Delete"
      }
    }
  }
}

output "bucket_names" {
  value = { for k, b in google_storage_bucket.b : k => b.name }
}
