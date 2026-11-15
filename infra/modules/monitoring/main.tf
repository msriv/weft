variable "project_id" { type = string }
variable "alert_email" {
  description = "Where alerts go."
  type        = string
}
variable "billing_account_id" {
  description = "Billing account for the project budget (id like 012345-6789AB-CDEF01). Empty skips the budget."
  type        = string
  default     = ""
}
variable "budget_usd" {
  description = "Monthly GCP budget in USD; alerts at 50%, 90% and 100%."
  type        = number
  default     = 100
}
variable "graph_node_limit" {
  description = "Node limit of the Neo4j AuraDB tier in use (free tier: 200000)."
  type        = number
  default     = 200000
}
locals {
  runbook = "infra/README.md#alerts"
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

# --- Failure alerts (#165). Each one's documentation names the runbook section. ---

resource "google_monitoring_alert_policy" "nightly_failed" {
  project      = var.project_id
  display_name = "Weft: nightly workflow failed"
  combiner     = "OR"
  conditions {
    display_name = "A weft-nightly execution finished FAILED"
    condition_threshold {
      filter          = "metric.type=\"workflows.googleapis.com/finished_execution_count\" AND resource.type=\"workflows.googleapis.com/Workflow\" AND resource.label.workflow_id=\"weft-nightly\" AND metric.label.status=\"FAILED\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period   = "600s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }
  documentation {
    content   = "The nightly pipeline failed. See ${local.runbook}: 'Nightly failed'."
    mime_type = "text/markdown"
  }
  notification_channels = [google_monitoring_notification_channel.email.id]
}

resource "google_monitoring_alert_policy" "backlog" {
  project      = var.project_id
  display_name = "Weft: Pub/Sub backlog"
  combiner     = "OR"
  conditions {
    display_name = "A subscription has had an unacknowledged message for 30 minutes"
    condition_threshold {
      filter          = "metric.type=\"pubsub.googleapis.com/subscription/oldest_unacked_message_age\" AND resource.type=\"pubsub_subscription\""
      comparison      = "COMPARISON_GT"
      threshold_value = 1800
      duration        = "300s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }
  documentation {
    content   = "Messages are waiting on a push subscription. See ${local.runbook}: 'Backlog'."
    mime_type = "text/markdown"
  }
  notification_channels = [google_monitoring_notification_channel.email.id]
}

resource "google_monitoring_alert_policy" "errors_5xx" {
  project      = var.project_id
  display_name = "Weft: Cloud Run 5xx rate"
  combiner     = "OR"
  conditions {
    display_name = "More than 5% of requests to a service are 5xx for 10 minutes"
    condition_threshold {
      filter             = "metric.type=\"run.googleapis.com/request_count\" AND resource.type=\"cloud_run_revision\" AND metric.label.response_code_class=\"5xx\""
      denominator_filter = "metric.type=\"run.googleapis.com/request_count\" AND resource.type=\"cloud_run_revision\""
      comparison         = "COMPARISON_GT"
      threshold_value    = 0.05
      duration           = "600s"
      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["resource.label.service_name"]
      }
      denominator_aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["resource.label.service_name"]
      }
    }
  }
  documentation {
    content   = "A service is returning errors. See ${local.runbook}: 'Error rate'."
    mime_type = "text/markdown"
  }
  notification_channels = [google_monitoring_notification_channel.email.id]
}

# The model client prints budget_high (80% of a daily cap) and budget_exceeded (cap reached).
resource "google_logging_metric" "budget" {
  project = var.project_id
  name    = "weft_model_budget"
  filter  = "jsonPayload.event=(\"budget_high\" OR \"budget_exceeded\")"
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    labels {
      key        = "event"
      value_type = "STRING"
    }
  }
  label_extractors = { event = "EXTRACT(jsonPayload.event)" }
}

resource "google_monitoring_alert_policy" "model_budget" {
  project      = var.project_id
  display_name = "Weft: model spend near or at the daily cap"
  combiner     = "OR"
  conditions {
    display_name = "A caller used 80% or all of its daily model budget"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.budget.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period   = "900s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }
  documentation {
    content   = "Claims, merge checks or Ask may be degrading. See ${local.runbook}: 'Model budget'."
    mime_type = "text/markdown"
  }
  notification_channels = [google_monitoring_notification_channel.email.id]
}

resource "google_project_service" "billingbudgets" {
  count              = var.billing_account_id == "" ? 0 : 1
  project            = var.project_id
  service            = "billingbudgets.googleapis.com"
  disable_on_destroy = false
}

data "google_project" "this" {
  project_id = var.project_id
}

resource "google_billing_budget" "project" {
  count           = var.billing_account_id == "" ? 0 : 1
  billing_account = var.billing_account_id
  display_name    = "Weft project budget"
  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }
  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.budget_usd)
    }
  }
  threshold_rules { threshold_percent = 0.5 }
  threshold_rules { threshold_percent = 0.9 }
  threshold_rules { threshold_percent = 1.0 }
  all_updates_rule {
    monitoring_notification_channels = [google_monitoring_notification_channel.email.id]
    disable_default_iam_recipients   = true
  }
  depends_on = [google_project_service.billingbudgets]
}

# The nightly run prints one graph_size line (nodes, relationships, by label).
resource "google_logging_metric" "graph_nodes" {
  project = var.project_id
  name    = "weft_graph_nodes"
  filter  = "jsonPayload.event=\"graph_size\""
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "DISTRIBUTION"
  }
  value_extractor = "EXTRACT(jsonPayload.nodes)"
  bucket_options {
    exponential_buckets {
      num_finite_buckets = 40
      growth_factor      = 1.5
      scale              = 1000
    }
  }
}

resource "google_monitoring_alert_policy" "graph_size" {
  project      = var.project_id
  display_name = "Weft: graph above 70% of the Neo4j tier limit"
  combiner     = "OR"
  conditions {
    display_name = "Node count above 70% of ${var.graph_node_limit}"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.graph_nodes.name}\" AND resource.type=\"cloud_run_job\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.graph_node_limit * 0.7
      duration        = "0s"
      aggregations {
        alignment_period     = "86400s"
        per_series_aligner   = "ALIGN_PERCENTILE_99"
        cross_series_reducer = "REDUCE_MAX"
      }
    }
  }
  documentation {
    content   = "Writes fail at the tier limit. See ${local.runbook}: 'Graph size'."
    mime_type = "text/markdown"
  }
  notification_channels = [google_monitoring_notification_channel.email.id]
}

resource "google_monitoring_dashboard" "operations" {
  project = var.project_id
  dashboard_json = jsonencode({
    displayName = "Weft operations"
    mosaicLayout = {
      columns = 12
      tiles = [
        {
          width  = 6
          height = 4
          widget = {
            title = "Oldest unacknowledged message (seconds), per subscription"
            xyChart = {
              dataSets = [{
                plotType = "LINE"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"pubsub.googleapis.com/subscription/oldest_unacked_message_age\" resource.type=\"pubsub_subscription\""
                    aggregation = {
                      alignmentPeriod  = "300s"
                      perSeriesAligner = "ALIGN_MAX"
                    }
                  }
                }
              }]
            }
          }
        },
        {
          xPos   = 6
          width  = 6
          height = 4
          widget = {
            title = "Items by status per hour (stored, duplicate, dead, deferred, refused)"
            xyChart = {
              dataSets = [{
                plotType = "STACKED_BAR"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.items_processed.name}\""
                    aggregation = {
                      alignmentPeriod    = "3600s"
                      perSeriesAligner   = "ALIGN_SUM"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["metric.label.status"]
                    }
                  }
                }
              }]
            }
          }
        },
        {
          yPos   = 4
          width  = 6
          height = 4
          widget = {
            title = "Graph nodes (nightly)"
            xyChart = {
              dataSets = [{
                plotType = "LINE"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.graph_nodes.name}\""
                    aggregation = {
                      alignmentPeriod    = "86400s"
                      perSeriesAligner   = "ALIGN_PERCENTILE_99"
                      crossSeriesReducer = "REDUCE_MAX"
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
