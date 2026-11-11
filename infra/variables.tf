variable "project_id" {
  description = "GCP project for this environment."
  type        = string
  default     = "weft-news-prod"
}

variable "region" {
  description = "GCP region for every resource. Changing it is a variable change."
  type        = string
  default     = "asia-south1"
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
  description = "Recipient for alert policies."
  type        = string
}

variable "crawler_image" {
  description = "Crawler image in Artifact Registry. Built in CI, not by hand."
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
  description = "OpenAI-compatible endpoint for the hosted open-weight models (OpenRouter)."
  type        = string
  default     = "https://openrouter.ai/api/v1"
}

variable "model_name" {
  description = "Model slug at the provider. Open-weight; revision pins the weights."
  type        = string
  default     = "qwen/qwen3.6-35b-a3b"
}

variable "model_revision" {
  description = "Pinned model revision (Hugging Face commit hash of model_name)."
  type        = string
  default     = "995ad96eacd98c81ed38be0c5b274b04031597b0"
}

variable "model_provider" {
  description = "OpenRouter only: upstream host to pin. Empty for other providers."
  type        = string
  default     = "DeepInfra"
}

variable "api_image" {
  description = "API image in Artifact Registry. Built in CI, not by hand."
  type        = string
}

variable "web_image" {
  description = "Web app image in Artifact Registry. Built in CI, not by hand."
  type        = string
}

# Email digest (Resend over SMTP). Empty smtp_host turns the digest off.
variable "smtp_host" {
  type    = string
  default = ""
}

variable "smtp_user" {
  type    = string
  default = ""
}

variable "mail_from" {
  type    = string
  default = ""
}

variable "firebase_api_key" {
  description = "Firebase web API key (public by design). Create it in the Firebase console once Identity Platform is enabled; leave empty to keep reader sign-in off."
  type        = string
  default     = ""
}
