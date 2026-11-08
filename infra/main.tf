module "storage" {
  source             = "./modules/storage"
  project_id         = var.project_id
  region             = var.region
  raw_retention_days = var.raw_retention_days
}

locals {
  # shortcut: ":latest" does not redeploy on a new build; build_images.sh pins a tag via images.auto.tfvars
  images = {
    poller        = coalesce(var.poller_image, "${var.region}-docker.pkg.dev/${var.project_id}/weft/poller:latest")
    fetcher       = coalesce(var.fetcher_image, "${var.region}-docker.pkg.dev/${var.project_id}/weft/fetcher:latest")
    crawler       = coalesce(var.crawler_image, "${var.region}-docker.pkg.dev/${var.project_id}/weft/crawler:latest")
    discovery     = coalesce(var.discovery_image, "${var.region}-docker.pkg.dev/${var.project_id}/weft/discovery:latest")
    stream_worker = coalesce(var.stream_worker_image, "${var.region}-docker.pkg.dev/${var.project_id}/weft/stream_worker:latest")
    nightly       = coalesce(var.nightly_image, "${var.region}-docker.pkg.dev/${var.project_id}/weft/nightly:latest")
    api           = coalesce(var.api_image, "${var.region}-docker.pkg.dev/${var.project_id}/weft/api:latest")
    web           = coalesce(var.web_image, "${var.region}-docker.pkg.dev/${var.project_id}/weft/web:latest")
  }
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
  image                 = local.images.poller
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
  image                 = local.images.fetcher
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
  image                 = local.images.crawler
  service_account_email = module.platform.service_account_emails["crawler"]
  raw_bucket            = module.storage.bucket_names["weft-raw"]
  state_bucket          = module.storage.bucket_names["weft-snapshots"]
  dataset_id            = module.bigquery.dataset_id
  documents_topic       = module.messaging.topic_names["documents-new"]
  turso_secret_ids      = module.discovery.turso_secret_ids
}

module "discovery" {
  source                = "./modules/discovery"
  project_id            = var.project_id
  region                = var.region
  image                 = local.images.discovery
  service_account_email = module.platform.service_account_emails["discovery"]
}

module "stream_worker" {
  source                = "./modules/run_service"
  project_id            = var.project_id
  region                = var.region
  name                  = "weft-stream-worker"
  image                 = local.images.stream_worker
  service_account_email = module.platform.service_account_emails["stream-worker"]
  secret_env            = module.discovery.turso_secret_ids
  env                   = { PROJECT_ID = var.project_id, WEFT_NLP = "real" }
  memory                = "4Gi"
  cpu                   = "2"
  concurrency           = 4
  push_topic            = module.messaging.topic_names["items-extracted"]
  extra_pushes          = { documents = { topic = module.messaging.topic_names["documents-new"], path = "/documents" } }
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

resource "google_secret_manager_secret" "model_api_key" {
  project   = var.project_id
  secret_id = "weft-model-api-key"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "smtp_password" {
  project   = var.project_id
  secret_id = "weft-smtp-password"
  replication {
    auto {}
  }
}

module "nightly" {
  source                = "./modules/nightly"
  project_id            = var.project_id
  region                = var.region
  image                 = local.images.nightly
  service_account_email = module.platform.service_account_emails["nightly"]
  stages                = ["regroup", "claims", "figures", "claim_groups", "conflicts", "short_version", "statements", "anomalies", "weights", "snapshot", "review_sample", "notify"]
  secret_env = merge(module.discovery.turso_secret_ids, {
    MODEL_API_KEY = google_secret_manager_secret.model_api_key.secret_id
  }, var.smtp_host == "" ? {} : { SMTP_PASSWORD = google_secret_manager_secret.smtp_password.secret_id })
  env = merge({
    PROJECT_ID      = var.project_id
    RAW_BUCKET      = module.storage.bucket_names["weft-raw"]
    SNAPSHOT_BUCKET = module.storage.bucket_names["weft-snapshots"]
    MODEL_BASE_URL  = var.model_base_url
    MODEL_NAME      = var.model_name
    MODEL_REVISION  = var.model_revision
    MODEL_PROVIDER  = var.model_provider
    WEFT_NLP        = "real"
    }, var.smtp_host == "" ? {} : {
    SMTP_HOST = var.smtp_host
    SMTP_USER = var.smtp_user
    MAIL_FROM = var.mail_from
    SITE_URL  = module.web.uri
  })
}

resource "google_storage_bucket_iam_member" "nightly_raw_read" {
  bucket = module.storage.bucket_names["weft-raw"]
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${module.platform.service_account_emails["nightly"]}"
}

# model_calls are written by every service that calls a model (rule 4)
resource "google_bigquery_dataset_iam_member" "model_logging_bq" {
  for_each   = toset(["nightly", "api"])
  project    = var.project_id
  dataset_id = module.bigquery.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${module.platform.service_account_emails[each.key]}"
}

resource "google_project_iam_member" "model_logging_bq_jobs" {
  for_each = toset(["nightly", "api"])
  project  = var.project_id
  role     = "roles/bigquery.jobUser"
  member   = "serviceAccount:${module.platform.service_account_emails[each.key]}"
}

resource "google_storage_bucket_iam_member" "nightly_snapshots_write" {
  bucket = module.storage.bucket_names["weft-snapshots"]
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${module.platform.service_account_emails["nightly"]}"
}

module "api" {
  source                = "./modules/run_service"
  project_id            = var.project_id
  region                = var.region
  name                  = "weft-api"
  image                 = local.images.api
  service_account_email = module.platform.service_account_emails["api"]
  secret_env = merge(module.discovery.turso_secret_ids, {
    ADMIN_TOKEN   = module.discovery.admin_token_secret_id
    MODEL_API_KEY = google_secret_manager_secret.model_api_key.secret_id
  })
  env = {
    PROJECT_ID     = var.project_id
    MODEL_BASE_URL = var.model_base_url
    MODEL_NAME     = var.model_name
    MODEL_REVISION = var.model_revision
    MODEL_PROVIDER = var.model_provider
    WEFT_NLP       = "real"
  }
  memory        = "4Gi"
  public        = true
  max_instances = 5
}

module "web" {
  source                = "./modules/run_service"
  project_id            = var.project_id
  region                = var.region
  name                  = "weft-web"
  image                 = local.images.web
  service_account_email = module.platform.service_account_emails["web"]
  env                   = { API_URL = module.api.uri }
  public                = true
  max_instances         = 5
}

output "web_url" { value = module.web.uri }
