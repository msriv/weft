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

module "poller" {
  source                = "./modules/poller"
  project_id            = var.project_id
  region                = var.region
  image                 = var.poller_image
  service_account_email = module.platform.service_account_emails["poller"]
  state_bucket          = module.storage.bucket_names["weft-snapshots"]
  items_new_topic       = module.messaging.topic_names["items-new"]
}

module "fetcher" {
  source                = "./modules/fetcher"
  project_id            = var.project_id
  region                = var.region
  image                 = var.fetcher_image
  service_account_email = module.platform.service_account_emails["fetcher"]
  raw_bucket            = module.storage.bucket_names["weft-raw"]
  dataset_id            = module.bigquery.dataset_id
  items_new_topic       = module.messaging.topic_names["items-new"]
}
