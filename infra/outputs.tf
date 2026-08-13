output "project_id" {
  value = var.project_id
}

output "service_accounts" {
  description = "Attach each to its own runtime. None of them is a general purpose identity."
  value = {
    pipeline = google_service_account.pipeline.email
    tools    = google_service_account.tools.email
    webhooks = google_service_account.webhooks.email
    web      = google_service_account.web.email
  }
}

output "buckets" {
  value = {
    scripts       = google_storage_bucket.scripts.name
    evidence      = google_storage_bucket.evidence.name
    reports       = google_storage_bucket.reports.name
    agent_staging = google_storage_bucket.agent_staging.name
  }
}

output "bigquery" {
  value = {
    dataset          = google_bigquery_dataset.truestory.dataset_id
    cost_telemetry   = google_bigquery_table.cost_telemetry.table_id
    eval_results     = google_bigquery_table.eval_results.table_id
    precedent_corpus = google_bigquery_table.precedent_corpus.table_id
  }
}

output "pubsub" {
  value = {
    research    = google_pubsub_topic.research.name
    alerts      = google_pubsub_topic.alerts.name
    dead_letter = google_pubsub_topic.dead_letter.name
  }
}

output "secrets" {
  description = "Created empty. Add the values by hand, they never enter Terraform state."
  value = {
    parallel_api_key = google_secret_manager_secret.parallel_api_key.secret_id
    webhook_secret   = google_secret_manager_secret.webhook_secret.secret_id
    internal_token   = google_secret_manager_secret.internal_token.secret_id
  }
}

output "env_fragment" {
  description = "Paste into .env after the first apply."
  value       = <<-EOT
    GOOGLE_CLOUD_PROJECT=${var.project_id}
    GOOGLE_CLOUD_LOCATION=${var.region}
    GCS_BUCKET_SCRIPTS=${google_storage_bucket.scripts.name}
    GCS_BUCKET_EVIDENCE=${google_storage_bucket.evidence.name}
    GCS_BUCKET_REPORTS=${google_storage_bucket.reports.name}
    AGENT_ENGINE_STAGING_BUCKET=gs://${google_storage_bucket.agent_staging.name}
    BIGQUERY_DATASET=${google_bigquery_dataset.truestory.dataset_id}
    PUBSUB_TOPIC_RESEARCH=${google_pubsub_topic.research.name}
    PUBSUB_TOPIC_ALERTS=${google_pubsub_topic.alerts.name}
    CLOUD_TASKS_QUEUE=${google_cloud_tasks_queue.retry.name}
  EOT
}

output "next_steps" {
  value = <<-EOT

    1. Add the secret values, they are created empty on purpose:
         echo -n "YOUR_PARALLEL_KEY" | gcloud secrets versions add truestory-parallel-api-key --data-file=-
         openssl rand -hex 32 | tr -d '\n' | gcloud secrets versions add truestory-parallel-webhook-secret --data-file=-

    2. Deploy the services:
         make deploy-webhooks   # do this first, it gives you the callback URL
         make deploy-mcp
         make deploy-agent
         make deploy-web

    3. Reapply with the webhook URL so the scheduler can reach the sweep:
         terraform apply -var="project_id=${var.project_id}" -var="webhook_service_url=https://..."

    4. Deploy the Firestore security rules. Per project isolation belongs in
       the rules, not only in application code:
         firebase deploy --only firestore:rules

  EOT
}
