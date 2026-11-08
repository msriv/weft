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
  description = "Override the poller image. Empty uses :latest from Artifact Registry; build_images.sh pins a tag in images.auto.tfvars."
  type        = string
  default     = ""
}

variable "fetcher_image" {
  description = "Override the fetcher image. Empty uses :latest from Artifact Registry; build_images.sh pins a tag in images.auto.tfvars."
  type        = string
  default     = ""
}

variable "alert_email" {
  description = "Recipient for alert policies."
  type        = string
  default     = "msriv574@gmail.com"
}

variable "crawler_image" {
  description = "Override the crawler image. Empty uses :latest from Artifact Registry; build_images.sh pins a tag in images.auto.tfvars."
  type        = string
  default     = ""
}

variable "discovery_image" {
  description = "Override the discovery image. Empty uses :latest from Artifact Registry; build_images.sh pins a tag in images.auto.tfvars."
  type        = string
  default     = ""
}

variable "stream_worker_image" {
  description = "Override the stream_worker image. Empty uses :latest from Artifact Registry; build_images.sh pins a tag in images.auto.tfvars."
  type        = string
  default     = ""
}

variable "nightly_image" {
  description = "Override the nightly image. Empty uses :latest from Artifact Registry; build_images.sh pins a tag in images.auto.tfvars."
  type        = string
  default     = ""
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
  description = "Override the api image. Empty uses :latest from Artifact Registry; build_images.sh pins a tag in images.auto.tfvars."
  type        = string
  default     = ""
}

variable "web_image" {
  description = "Override the web image. Empty uses :latest from Artifact Registry; build_images.sh pins a tag in images.auto.tfvars."
  type        = string
  default     = ""
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
