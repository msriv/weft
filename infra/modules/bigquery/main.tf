variable "project_id" { type = string }
variable "region" { type = string }

locals {
  # table => time column for day partitioning, partition expiry in days (null = keep), and
  # deletion protection. `model_evals` stays; `batch_runs` is never written (stage runs are
  # BatchRun nodes in Neo4j, #153): it is unprotected so the next apply can drop it by removing
  # the entry here and its schema file. Raw article text is not kept here: model_calls.input is
  # nulled past raw retention by autoclean (rule 5).
  tables = {
    raw_items       = { field = "fetched_at", expire_days = null, cluster = ["canonical_url"], protect = true }
    extracted_items = { field = "extracted_at", expire_days = 400, cluster = null, protect = true } # summary is a 500-char lede
    model_calls     = { field = "called_at", expire_days = null, cluster = null, protect = true }
    batch_runs      = { field = "started_at", expire_days = null, cluster = null, protect = false }
    source_health   = { field = "checked_at", expire_days = 90, cluster = null, protect = true }
    model_evals     = { field = "evaluated_at", expire_days = null, cluster = null, protect = true }
  }
}

resource "google_bigquery_dataset" "weft" {
  project    = var.project_id
  dataset_id = "weft"
  location   = var.region
}

resource "google_bigquery_table" "t" {
  for_each            = local.tables
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.weft.dataset_id
  table_id            = each.key
  schema              = file("${path.module}/schemas/${each.key}.json")
  deletion_protection = each.value.protect
  clustering          = each.value.cluster

  time_partitioning {
    type          = "DAY"
    field         = each.value.field
    expiration_ms = each.value.expire_days == null ? null : each.value.expire_days * 86400000
  }
}

output "dataset_id" {
  value = google_bigquery_dataset.weft.dataset_id
}
