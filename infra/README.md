# infra

All GCP infrastructure is Terraform. No console clicks.

1. Create the state bucket once: `cd bootstrap && terraform apply -var project_id=weft-news-prod`.
2. `cp terraform.tfvars.example terraform.tfvars` and fill in the project, alert email and mail sender.
3. `terraform init -backend-config="bucket=<state bucket from step 1>"` then `terraform apply`.

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
