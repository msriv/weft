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
