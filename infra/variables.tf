variable "project_id" {
  description = "GCP project for this environment, e.g. weft-dev."
  type        = string
}

variable "region" {
  description = "GCP region for every resource. PLACEHOLDER until the owner picks one (issue #2); changing it is a variable change."
  type        = string
}

variable "raw_retention_days" {
  description = "Raw article copies are private, processing-only (product rule 5)."
  type        = number
  default     = 30
}

variable "poller_image" {
  description = "Poller image, e.g. <region>-docker.pkg.dev/<project>/weft/poller:<tag>. Built in CI, not by hand."
  type        = string
}

variable "fetcher_image" {
  description = "Fetcher image in Artifact Registry. Built in CI, not by hand."
  type        = string
}

variable "alert_email" {
  description = "Recipient for alert policies. PLACEHOLDER until the owner decides who is on call."
  type        = string
}
