module "storage" {
  source             = "./modules/storage"
  project_id         = var.project_id
  region             = var.region
  raw_retention_days = var.raw_retention_days
}

module "bigquery" {
  source     = "./modules/bigquery"
  project_id = var.project_id
  region     = var.region
}

module "messaging" {
  source     = "./modules/messaging"
  project_id = var.project_id
}

module "platform" {
  source     = "./modules/platform"
  project_id = var.project_id
  region     = var.region
}
