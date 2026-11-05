# Terraform root for all GCP infrastructure. One module per concern under modules/.
# State lives in GCS: create the bucket once with bootstrap/, then
#   terraform init -backend-config="bucket=<state bucket>"
terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  backend "gcs" {
    prefix = "weft-dev"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
