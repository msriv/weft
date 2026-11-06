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

variable "crawler_image" {
  description = "Crawler image in Artifact Registry. Built in CI, not by hand."
  type        = string
}

variable "gdelt_theme_regex" {
  description = "Regex over GDELT themes for the first beat. PLACEHOLDER until the beat is chosen (issue #1)."
  type        = string
}

variable "discovery_image" {
  description = "Discovery image, e.g. <region>-docker.pkg.dev/<project>/weft/discovery:<tag>. Built in CI, not by hand."
  type        = string
}

variable "stream_worker_image" {
  description = "Stream worker image in Artifact Registry. Built in CI, not by hand."
  type        = string
}

variable "nightly_image" {
  description = "Nightly pipeline image in Artifact Registry. Built in CI, not by hand."
  type        = string
}

variable "model_base_url" {
  description = "OpenAI-compatible endpoint for the hosted open-weight models. PLACEHOLDER until the provider is chosen (issue #3)."
  type        = string
}

variable "model_name" {
  description = "Pinned model name, e.g. Qwen/Qwen3-14B."
  type        = string
  default     = "Qwen/Qwen3-14B"
}

variable "model_revision" {
  description = "Pinned model revision (Hugging Face commit hash). PLACEHOLDER until the provider is chosen."
  type        = string
}

variable "api_image" {
  description = "API image in Artifact Registry. Built in CI, not by hand."
  type        = string
}

variable "web_image" {
  description = "Web app image in Artifact Registry. Built in CI, not by hand."
  type        = string
}
