# infra

All GCP infrastructure is Terraform. No console clicks.

1. Create the state bucket once: `cd bootstrap && terraform apply -var project_id=weft-news-prod`.
2. `cp terraform.tfvars.example terraform.tfvars` and fill in the project, alert email and mail sender.
3. `terraform init -backend-config="bucket=<state bucket from step 1>"` then `terraform apply`.

`region` defaults to `asia-south1` (set in `variables.tf`).

## Nightly stage list

The stage order lives in `config/pipeline.yaml` under `stages` (name and `needs`). `pipeline/run.py` and the Terraform in `infra/modules/nightly` both read it; `tests/test_stage_list.py` checks it against `pipeline/run.py` `STAGES`. The workflow runs every stage as its own job execution, skips a stage only when a stage in its `needs` failed, and ends the execution as failed if any stage failed or was skipped.
