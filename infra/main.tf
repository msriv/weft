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
  bot_contact_url       = var.bot_contact_url
  neo4j_secret_ids      = module.discovery.neo4j_secret_ids
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
  bot_contact_url       = var.bot_contact_url
  neo4j_secret_ids      = module.discovery.neo4j_secret_ids
  project_id            = var.project_id
  region                = var.region
  image                 = var.fetcher_image
  service_account_email = module.platform.service_account_emails["fetcher"]
  raw_bucket            = module.storage.bucket_names["weft-raw"]
  dataset_id            = module.bigquery.dataset_id
  items_new_topic       = module.messaging.topic_names["items-new"]
  depends_on            = [google_project_iam_member.pubsub_dead_letter_ack]
}

module "monitoring" {
  source             = "./modules/monitoring"
  project_id         = var.project_id
  alert_email        = var.alert_email
  billing_account_id = var.billing_account_id
  graph_node_limit   = var.graph_node_limit
}

module "crawler" {
  source                = "./modules/crawler"
  bot_contact_url       = var.bot_contact_url
  project_id            = var.project_id
  region                = var.region
  image                 = var.crawler_image
  service_account_email = module.platform.service_account_emails["crawler"]
  raw_bucket            = module.storage.bucket_names["weft-raw"]
  state_bucket          = module.storage.bucket_names["weft-snapshots"]
  dataset_id            = module.bigquery.dataset_id
  documents_topic       = module.messaging.topic_names["documents-new"]
  neo4j_secret_ids      = module.discovery.neo4j_secret_ids
}

module "discovery" {
  source                = "./modules/discovery"
  bot_contact_url       = var.bot_contact_url
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
  secret_env            = module.discovery.neo4j_secret_ids
  env                   = { PROJECT_ID = var.project_id, WEFT_NLP = "real" }
  memory                = "4Gi"
  cpu                   = "2"
  concurrency           = 4
  push_topic            = module.messaging.topic_names["items-extracted"]
  extra_pushes          = { documents = { topic = module.messaging.topic_names["documents-new"], path = "/documents" } }
  depends_on            = [google_project_iam_member.pubsub_dead_letter_ack]
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

locals {
  # nightly and autoclean run the same image with the same settings
  pipeline_secret_env = merge(module.discovery.neo4j_secret_ids, {
    MODEL_API_KEY = google_secret_manager_secret.model_api_key.secret_id
  }, var.smtp_host == "" ? {} : { SMTP_PASSWORD = google_secret_manager_secret.smtp_password.secret_id })
  pipeline_env = merge({
    PROJECT_ID         = var.project_id
    RAW_BUCKET         = module.storage.bucket_names["weft-raw"]
    SNAPSHOT_BUCKET    = module.storage.bucket_names["weft-snapshots"]
    RAW_RETENTION_DAYS = tostring(var.raw_retention_days) # autoclean follows the bucket lifecycle
    MODEL_BASE_URL     = var.model_base_url
    MODEL_NAME         = var.model_name
    MODEL_REVISION     = var.model_revision
    MODEL_PROVIDER     = var.model_provider
    WEFT_NLP           = "real"
    }, var.smtp_host == "" ? {} : {
    SMTP_HOST = var.smtp_host
    SMTP_USER = var.smtp_user
    MAIL_FROM = var.mail_from
    SITE_URL  = module.web.uri
  })
}

module "nightly" {
  source                = "./modules/nightly"
  project_id            = var.project_id
  region                = var.region
  image                 = var.nightly_image
  service_account_email = module.platform.service_account_emails["nightly"]
  stages                = yamldecode(file("${path.root}/../config/pipeline.yaml")).stages
  secret_env            = local.pipeline_secret_env
  env                   = local.pipeline_env
}

# Autoclean (#146): the same image, run alone on its own schedule after the nightly and its
# 4-hour window. Daily by default; weekly is "0 6 * * 0". Rules ship in dry_run
# (config/autoclean.yaml), so this changes nothing until a rule is switched to apply.
module "autoclean" {
  source                = "./modules/run_job"
  project_id            = var.project_id
  region                = var.region
  name                  = "weft-autoclean"
  image                 = var.nightly_image
  service_account_email = module.platform.service_account_emails["nightly"]
  command               = ["--stage", "autoclean"]
  env                   = local.pipeline_env
  secret_env            = local.pipeline_secret_env
  schedule              = var.autoclean_schedule
  timeout               = "3600s"
}

# Autoclean re-queues items that were stored but never placed (#150).
resource "google_pubsub_topic_iam_member" "autoclean_publish" {
  for_each = toset(["items-extracted", "documents-new"])
  project  = var.project_id
  topic    = module.messaging.topic_names[each.key]
  role     = "roles/pubsub.publisher"
  member   = "serviceAccount:${module.platform.service_account_emails["nightly"]}"
}

# Pub/Sub's service account must be able to ack a message it moves to a dead-letter topic.
data "google_project" "this" {
  project_id = var.project_id
}

resource "google_project_iam_member" "pubsub_dead_letter_ack" {
  project = var.project_id
  role    = "roles/pubsub.subscriber"
  member  = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
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

# Reader accounts: Firebase Authentication (Identity Platform) and Firestore preferences.
resource "google_project_service" "accounts" {
  for_each = toset(["firestore.googleapis.com", "identitytoolkit.googleapis.com"])
  project  = var.project_id
  service  = each.key
}

resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"
  depends_on  = [google_project_service.accounts]
}

resource "google_identity_platform_config" "auth" {
  project = var.project_id
  sign_in {
    email {
      enabled           = true
      password_required = true
    }
  }
  depends_on = [google_project_service.accounts]
}

resource "google_project_iam_member" "api_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${module.platform.service_account_emails["api"]}"
}

# Shared secret the web proxy signs the browser's address with, so the API's rate limits (#158)
# can tell readers apart and a direct caller cannot forge an address. Generated here, no manual step.
resource "random_password" "proxy_secret" {
  length  = 40
  special = false
}

resource "google_secret_manager_secret" "proxy_secret" {
  project   = var.project_id
  secret_id = "weft-proxy-secret"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "proxy_secret" {
  secret      = google_secret_manager_secret.proxy_secret.id
  secret_data = random_password.proxy_secret.result
}

module "api" {
  source                = "./modules/run_service"
  project_id            = var.project_id
  region                = var.region
  name                  = "weft-api"
  image                 = var.api_image
  service_account_email = module.platform.service_account_emails["api"]
  secret_env = merge(module.discovery.neo4j_secret_ids, {
    ADMIN_TOKEN   = module.discovery.admin_token_secret_id
    MODEL_API_KEY = google_secret_manager_secret.model_api_key.secret_id
    PROXY_SECRET  = google_secret_manager_secret.proxy_secret.secret_id
  })
  env = {
    PROJECT_ID     = var.project_id
    ADMIN_EMAILS   = join(",", var.admin_emails)
    MODEL_BASE_URL = var.model_base_url
    MODEL_NAME     = var.model_name
    MODEL_REVISION = var.model_revision
    MODEL_PROVIDER = var.model_provider
    WEFT_NLP       = "real"
  }
  memory        = "4Gi"
  public        = true
  max_instances = 5
  depends_on    = [google_secret_manager_secret_version.proxy_secret]
}

module "web" {
  source                = "./modules/run_service"
  project_id            = var.project_id
  region                = var.region
  name                  = "weft-web"
  image                 = var.web_image
  service_account_email = module.platform.service_account_emails["web"]
  secret_env            = { PROXY_SECRET = google_secret_manager_secret.proxy_secret.secret_id }
  env                   = { API_URL = module.api.uri, FIREBASE_API_KEY = var.firebase_api_key }
  public                = true
  max_instances         = 5
  depends_on            = [google_secret_manager_secret_version.proxy_secret]
}

output "web_url" { value = module.web.uri }
