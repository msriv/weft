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
  turso_secret_ids      = module.discovery.turso_secret_ids
  project_id            = var.project_id
  region                = var.region
  image                 = var.poller_image
  service_account_email = module.platform.service_account_emails["poller"]
  state_bucket          = module.storage.bucket_names["weft-snapshots"]
  dataset_id            = module.bigquery.dataset_id
  items_new_topic       = module.messaging.topic_names["items-new"]
}

module "fetcher" {
  source                = "./modules/fetcher"
  turso_secret_ids      = module.discovery.turso_secret_ids
  project_id            = var.project_id
  region                = var.region
  image                 = var.fetcher_image
  service_account_email = module.platform.service_account_emails["fetcher"]
  raw_bucket            = module.storage.bucket_names["weft-raw"]
  dataset_id            = module.bigquery.dataset_id
  items_new_topic       = module.messaging.topic_names["items-new"]
}

module "monitoring" {
  source      = "./modules/monitoring"
  project_id  = var.project_id
  alert_email = var.alert_email
}

module "crawler" {
  source                = "./modules/crawler"
  project_id            = var.project_id
  region                = var.region
  image                 = var.crawler_image
  service_account_email = module.platform.service_account_emails["crawler"]
  raw_bucket            = module.storage.bucket_names["weft-raw"]
  state_bucket          = module.storage.bucket_names["weft-snapshots"]
  dataset_id            = module.bigquery.dataset_id
}

module "gdelt" {
  source      = "./modules/gdelt"
  project_id  = var.project_id
  theme_regex = var.gdelt_theme_regex
}

module "discovery" {
  source                = "./modules/discovery"
  project_id            = var.project_id
  region                = var.region
  image                 = var.discovery_image
  service_account_email = module.platform.service_account_emails["discovery"]
}

module "stream_worker" {
  source                = "./modules/run_service"
  project_id            = var.project_id
  region                = var.region
  name                  = "weft-stream-worker"
  image                 = var.stream_worker_image
  service_account_email = module.platform.service_account_emails["stream-worker"]
  secret_env            = module.discovery.turso_secret_ids
  env                   = { PROJECT_ID = var.project_id, WEFT_NLP = "real" }
  memory                = "4Gi"
  cpu                   = "2"
  concurrency           = 4
  push_topic            = module.messaging.topic_names["items-extracted"]
}

resource "google_pubsub_topic_iam_member" "stream_publish" {
  project = var.project_id
  topic   = module.messaging.topic_names["graph-changed"]
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${module.platform.service_account_emails["stream-worker"]}"
}

resource "google_pubsub_topic_iam_member" "fetcher_publish" {
  project = var.project_id
  topic   = module.messaging.topic_names["items-extracted"]
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${module.platform.service_account_emails["fetcher"]}"
}
