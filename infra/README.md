# infra

All GCP infrastructure is Terraform. No console clicks.

1. Create the state bucket once: `cd bootstrap && terraform apply -var project_id=weft-news-prod`.
2. `cp terraform.tfvars.example terraform.tfvars` and fill in the project, alert email and mail sender.
3. `terraform init -backend-config="bucket=<state bucket from step 1>"` then `terraform apply`.

`region` defaults to `asia-south1` (set in `variables.tf`).
