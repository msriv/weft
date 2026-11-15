variable "project_id" { type = string }
variable "region" { type = string }
variable "raw_retention_days" { type = number }

locals {
  # weft-models: nothing writes to it yet (models come from the hosted API, D7). Kept for the
  # mirrored weights in docs/spec.md; remove it if D7 stays.
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

  # Dated snapshot folders (2026-11-14/...) move to cheaper storage and are never deleted: they
  # are Replay's long-term record. `poller-state/` and `crawler-state/` do not match "20".
  # Autoclean (orphan_state) removes state blobs of feeds that are gone.
  dynamic "lifecycle_rule" {
    for_each = each.key == "weft-snapshots" ? { NEARLINE = 30, COLDLINE = 180 } : {}
    content {
      condition {
        age            = lifecycle_rule.value
        matches_prefix = ["20"]
      }
      action {
        type          = "SetStorageClass"
        storage_class = lifecycle_rule.key
      }
    }
  }
}

output "bucket_names" {
  value = { for k, b in google_storage_bucket.b : k => b.name }
}
