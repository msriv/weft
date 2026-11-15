# infra

All GCP infrastructure is Terraform. No console clicks.

## Deploys

Nothing is deployed by hand. A pull request builds every image (no push) and shows a `terraform plan` summary; a merge to `main` runs `.github/workflows/deploy.yml`:

1. Build and push all 8 images in parallel, tagged with the commit SHA.
2. `terraform apply` with those tags. Every Cloud Run service and job then runs the merged commit.
3. Smoke check the site: `/`, `/api/openapi.json`, `/api/v1/stories` (through the web proxy).
4. On success the tags are saved to `gs://<state bucket>/deploy/images.auto.tfvars`. On a failed smoke check the saved previous tags are applied and the run fails.

The workflows use Workload Identity Federation: no key is stored anywhere. To gate deploys on a click, add required reviewers to the `production` environment in the repository settings.

### One-time bootstrap (the only manual step)

1. Create the state bucket and the federation: `cd bootstrap && terraform apply -var project_id=weft-news-prod` (local state, run once). Grant the printed `deploy_service_account` the `billing.costsManager` role on the billing account if you use the budget alerts.
2. Set these repository **variables** (not secrets) in GitHub: `GCP_PROJECT`, `GCP_REGION`, `WIF_PROVIDER` (output `workload_identity_provider`), `DEPLOY_SA` (output `deploy_service_account`), `TF_STATE_BUCKET` (output `state_bucket`), and `TFVARS` (the contents of your `terraform.tfvars`: project, alert email, mail sender, admin emails, billing account).
3. Create the secrets in Secret Manager as before (`weft-smtp-password`, `weft-model-api-key`, Neo4j credentials, `weft-admin-token`).

The first merge after that deploys everything. `build_images.sh` still works for building by hand from a laptop, but is no longer part of the flow.

`region` defaults to `asia-south1` (set in `variables.tf`).

## Neo4j tier

Record the AuraDB tier in use here (name, node and relationship limits) and set `graph_node_limit` to its node limit. The tier is not known to the repo. 

## Alerts

All alerts email `alert_email` and are created by Terraform (`modules/monitoring`). The project budget is created only when `billing_account_id` is set.

### Nightly failed
The `weft-nightly` Cloud Workflow finished FAILED. Open the execution in Cloud Workflows, find the failed stage (the pipeline stage name is in the error), then read its Cloud Run job logs. The admin page lists stage runs. Stages after a failed one are skipped when they depend on it; the next night retries everything.

### Backlog
A push subscription has had an unacknowledged message for 30 minutes. Check the subscriber (`fetcher`, `weft-stream-worker`) in Cloud Run: crash loops, cold starts, or a source holding the single fetcher slot. Messages are kept for 7 days, so a fix within that time loses nothing.

### Error rate
More than 5% of requests to one Cloud Run service were 5xx for 10 minutes. The alert's series names the service. Read its logs for `severity=ERROR`; `/readyz` failing means Neo4j is unreachable.

### Model budget
A caller (`ask` or `pipeline`) used 80% (`budget_high`) or all (`budget_exceeded`) of its daily cap from `config/pipeline.yaml` `model_budget`. At the cap, Ask answers 429 and nightly stages skip model calls (claims, merge checks). The cap resets at midnight UTC. Check `model_calls` in BigQuery for what spent it, and the OpenRouter key limit.

### Project budget
The GCP budget passed 50%, 90% or 100% of `budget_usd`. Check Billing reports by service.

### Graph size
The nightly `graph_size` line passed 70% of `graph_node_limit`. AuraDB writes fail at the tier limit. Upgrade the tier or prune (see the auto-clean issues); relationship counts are in the same log line.


## Nightly stage list

The stage order lives in `config/pipeline.yaml` under `stages` (name and `needs`). `pipeline/run.py` and the Terraform in `infra/modules/nightly` both read it; `tests/test_stage_list.py` checks it against `pipeline/run.py` `STAGES`. The workflow runs every stage as its own job execution, skips a stage only when a stage in its `needs` failed, and ends the execution as failed if any stage failed or was skipped.
