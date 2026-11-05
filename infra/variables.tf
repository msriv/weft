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
