variable "project_id" { type = string }
variable "theme_regex" {
  description = "RE2 regex over GDELT V2Themes selecting the beat. PLACEHOLDER until the first beat is chosen (issue #1)."
  type        = string
  validation {
    condition     = !strcontains(var.theme_regex, "\"\"\"")
    error_message = "theme_regex must not contain triple quotes (it is embedded in the query as a raw string)."
  }
}
variable "location" {
  description = "Location of the dataset. The public GDELT tables are in the US multi-region, and BigQuery cannot write query results across locations, so this stays US even if the rest of the stack uses another region."
  type        = string
  default     = "US"
}
variable "schedule" {
  type    = string
  default = "every 15 minutes" # GDELT 2.0 publishes every 15 minutes
}

resource "google_project_service" "transfer" {
  project            = var.project_id
  service            = "bigquerydatatransfer.googleapis.com"
  disable_on_destroy = false
}

resource "google_bigquery_dataset" "gdelt" {
  project    = var.project_id
  dataset_id = "weft_gdelt"
  location   = var.location
}

resource "google_bigquery_table" "candidates" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.gdelt.dataset_id
  table_id            = "gdelt_candidates"
  schema              = file("${path.module}/schema.json")
  deletion_protection = true

  time_partitioning {
    type  = "DAY"
    field = "discovered_at"
  }
}

resource "google_service_account" "query" {
  project      = var.project_id
  account_id   = "weft-gdelt"
  display_name = "Weft GDELT scheduled query"
}

resource "google_project_iam_member" "jobs" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.query.email}"
}

resource "google_bigquery_dataset_iam_member" "write" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.gdelt.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.query.email}"
}

resource "google_bigquery_data_transfer_config" "gdelt" {
  project                = var.project_id
  location               = var.location
  display_name           = "weft-gdelt-candidates"
  data_source_id         = "scheduled_query"
  schedule               = var.schedule
  destination_dataset_id = google_bigquery_dataset.gdelt.dataset_id
  service_account_name   = google_service_account.query.email

  params = {
    destination_table_name_template = google_bigquery_table.candidates.table_id
    write_disposition               = "WRITE_APPEND"
    query = templatefile("${path.module}/query.sql", {
      project_id  = var.project_id
      dataset_id  = google_bigquery_dataset.gdelt.dataset_id
      theme_regex = var.theme_regex
    })
  }

  depends_on = [google_project_service.transfer, google_project_iam_member.jobs]
}
