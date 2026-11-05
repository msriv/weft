variable "project_id" { type = string }
variable "region" { type = string }

locals {
  # table => time column used for day partitioning
  tables = {
    raw_items       = "fetched_at"
    extracted_items = "extracted_at"
    model_calls     = "called_at"
    batch_runs      = "started_at"
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
  deletion_protection = true

  time_partitioning {
    type  = "DAY"
    field = each.value
  }
}

output "dataset_id" {
  value = google_bigquery_dataset.weft.dataset_id
}
