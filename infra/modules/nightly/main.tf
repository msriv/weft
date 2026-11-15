# Nightly pipeline: one Cloud Run job image, one Cloud Workflows run per night that executes each
# stage as its own job execution (so a failed stage can be re-run alone), started by Cloud Scheduler.
variable "project_id" { type = string }
variable "region" { type = string }
variable "image" { type = string }
variable "service_account_email" { type = string }
variable "env" {
  type    = map(string)
  default = {}
}
variable "secret_env" {
  type    = map(string)
  default = {}
}
variable "stages" {
  description = "Stages in run order, from config/pipeline.yaml (the single source of truth). needs = stages whose failure skips this one."
  type = list(object({
    name  = string
    needs = list(string)
  }))
}
variable "schedule" {
  description = "Cron (UTC). The nightly window is 4 hours; start in the reader-quiet hours."
  type        = string
  default     = "0 1 * * *"
}

locals {
  job_timeout_s       = 7200
  connector_timeout_s = local.job_timeout_s + 300 # never shorter than the job
}

module "job" {
  source                = "../run_job"
  project_id            = var.project_id
  region                = var.region
  name                  = "weft-nightly"
  image                 = var.image
  service_account_email = var.service_account_email
  env                   = var.env
  secret_env            = var.secret_env
  timeout               = "${local.job_timeout_s}s"
  memory                = "8Gi"
  cpu                   = "4"
}

resource "google_project_service" "workflows" {
  for_each           = toset(["workflows.googleapis.com", "cloudscheduler.googleapis.com"])
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

resource "google_project_iam_member" "grants" {
  for_each = toset(["roles/run.developer", "roles/workflows.invoker", "roles/iam.serviceAccountUser"])
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${var.service_account_email}"
}

resource "google_workflows_workflow" "nightly" {
  project         = var.project_id
  region          = var.region
  name            = "weft-nightly"
  service_account = var.service_account_email
  source_contents = <<-EOT
    main:
      steps:
        - init:
            assign:
              - failed: []
        - each_stage:
            for:
              value: stage
              in: ${jsonencode(var.stages)}
              steps:
                - reset:
                    assign:
                      - blocked: false
                - check_needs:
                    for:
                      value: dep
                      in: $${stage.needs}
                      steps:
                        - is_failed:
                            switch:
                              - condition: $${dep in failed}
                                assign:
                                  - blocked: true
                - gate:
                    switch:
                      - condition: $${blocked}
                        steps:
                          - mark_skipped:
                              assign:
                                - failed: $${list.concat(failed, stage.name)}
                          - log_skipped:
                              call: sys.log
                              args:
                                severity: WARNING
                                text: $${"stage skipped, a needed stage failed - " + stage.name}
                          - skip:
                              next: continue
                - run_stage:
                    try:
                      call: googleapis.run.v2.projects.locations.jobs.run
                      args:
                        name: projects/${var.project_id}/locations/${var.region}/jobs/${module.job.name}
                        body:
                          overrides:
                            containerOverrides:
                              - args: ["--stage", "$${stage.name}"]
                      # Connector default is 1800 s; the job itself may run 7200 s (module.job timeout).
                      connector_params:
                        timeout: ${local.connector_timeout_s}
                    except:
                      as: e
                      steps:
                        - mark_failed:
                            assign:
                              - failed: $${list.concat(failed, stage.name)}
                        - log_failed:
                            call: sys.log
                            args:
                              severity: ERROR
                              text: $${"stage failed - " + stage.name}
        - finish:
            switch:
              - condition: $${len(failed) > 0}
                raise: $${"nightly stages failed or skipped - " + json.encode_to_string(failed)}
  EOT
  depends_on      = [google_project_service.workflows]
}

resource "google_cloud_scheduler_job" "nightly" {
  project   = var.project_id
  region    = var.region
  name      = "weft-nightly"
  schedule  = var.schedule
  time_zone = "Etc/UTC"
  http_target {
    http_method = "POST"
    uri         = "https://workflowexecutions.googleapis.com/v1/${google_workflows_workflow.nightly.id}/executions"
    body        = base64encode("{}")
    oauth_token {
      service_account_email = var.service_account_email
    }
  }
  depends_on = [google_project_service.workflows]
}
