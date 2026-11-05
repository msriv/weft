variable "project_id" { type = string }
variable "alert_email" {
  description = "Where feed-health alerts go. PLACEHOLDER until the owner names who is on call."
  type        = string
}

resource "google_project_service" "monitoring" {
  project            = var.project_id
  service            = "monitoring.googleapis.com"
  disable_on_destroy = false
}

resource "google_monitoring_notification_channel" "email" {
  project      = var.project_id
  display_name = "Weft alerts"
  type         = "email"
  labels       = { email_address = var.alert_email }
  depends_on   = [google_project_service.monitoring]
}

# The poller logs one ERROR line per unhealthy source on each run.
resource "google_logging_metric" "source_unhealthy" {
  project = var.project_id
  name    = "weft_source_unhealthy"
  filter  = "resource.type=\"cloud_run_job\" AND jsonPayload.event=\"source_unhealthy\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    labels {
      key        = "source_id"
      value_type = "STRING"
    }
  }
  label_extractors = { source_id = "EXTRACT(jsonPayload.source_id)" }
}

resource "google_monitoring_alert_policy" "source_unhealthy" {
  project      = var.project_id
  display_name = "Weft: source feed unhealthy"
  combiner     = "OR"

  conditions {
    display_name = "A source has had no successful poll for 6 hours"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.source_unhealthy.name}\" AND resource.type=\"cloud_run_job\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period   = "900s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.id]
}
