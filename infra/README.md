# infra

All GCP infrastructure is Terraform. No console clicks.

1. Create the state bucket once: `cd bootstrap && terraform apply -var project_id=weft-dev -var region=<region>`.
2. `cp terraform.tfvars.example terraform.tfvars` and set `region`.
3. `terraform init -backend-config="bucket=<state bucket from step 1>"` then `terraform apply`.

`region` has no default on purpose: the region decision (#2) is still open.
