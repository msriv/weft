variable "project_id" { type = string }
variable "alert_email" {
  description = "Where feed-health alerts go."
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

# Fetcher logs one `item_processed` line per message: status is stored, duplicate,
# extract_failed or skipped.
resource "google_logging_metric" "items_processed" {
  project = var.project_id
  name    = "weft_items_processed"
  filter  = "resource.type=\"cloud_run_revision\" AND jsonPayload.event=\"item_processed\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    labels {
      key        = "source_id"
      value_type = "STRING"
    }
    labels {
      key        = "status"
      value_type = "STRING"
    }
  }
  label_extractors = {
    source_id = "EXTRACT(jsonPayload.source_id)"
    status    = "EXTRACT(jsonPayload.status)"
  }
}

resource "google_monitoring_dashboard" "ingestion" {
  project = var.project_id
  dashboard_json = jsonencode({
    displayName = "Weft ingestion"
    mosaicLayout = {
      columns = 12
      tiles = [
        {
          width  = 12
          height = 4
          widget = {
            title = "Items stored per source per hour"
            xyChart = {
              dataSets = [{
                plotType = "STACKED_BAR"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.items_processed.name}\" metric.label.status=\"stored\""
                    aggregation = {
                      alignmentPeriod    = "3600s"
                      perSeriesAligner   = "ALIGN_SUM"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["metric.label.source_id"]
                    }
                  }
                }
              }]
            }
          }
        },
        {
          yPos   = 4
          width  = 12
          height = 4
          widget = {
            title = "Extraction failures per source per hour"
            xyChart = {
              dataSets = [{
                plotType = "STACKED_BAR"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.items_processed.name}\" metric.label.status=\"extract_failed\""
                    aggregation = {
                      alignmentPeriod    = "3600s"
                      perSeriesAligner   = "ALIGN_SUM"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["metric.label.source_id"]
                    }
                  }
                }
              }]
            }
          }
        },
      ]
    }
  })
}

# Autoclean logs one ERROR line when a rule aborts (over its cap) or fails.
resource "google_logging_metric" "autoclean_problem" {
  project = var.project_id
  name    = "weft_autoclean_problem"
  filter  = "resource.type=\"cloud_run_job\" AND jsonPayload.event=(\"autoclean_aborted\" OR \"autoclean_failed\")"

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    labels {
      key        = "rule"
      value_type = "STRING"
    }
  }
  label_extractors = { rule = "EXTRACT(jsonPayload.rule)" }
}

resource "google_monitoring_alert_policy" "autoclean_problem" {
  project      = var.project_id
  display_name = "Weft: an autoclean rule aborted or failed"
  combiner     = "OR"

  conditions {
    display_name = "autoclean_aborted or autoclean_failed in the logs"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.autoclean_problem.name}\" AND resource.type=\"cloud_run_job\""
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

# Messages that failed delivery 10 times wait in a `*-dead-pull` subscription (modules/dead_letter).
resource "google_monitoring_alert_policy" "dead_letter" {
  project      = var.project_id
  display_name = "Weft: messages in a dead-letter queue"
  combiner     = "OR"

  conditions {
    display_name = "A dead-letter subscription holds messages"
    condition_threshold {
      filter          = "metric.type=\"pubsub.googleapis.com/subscription/num_undelivered_messages\" AND resource.type=\"pubsub_subscription\" AND resource.label.subscription_id=monitoring.regex.full_match(\".*-dead-pull\")"
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "300s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.id]
}
