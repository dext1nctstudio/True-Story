# =============================================================================
# TRUE STORY  ·  Google Cloud infrastructure
# =============================================================================
# Every Google Cloud service this project uses is created here, which is also
# the checkable answer to the submission requirement that the integration be
# real runtime use rather than a name in a README.
#
#   terraform init
#   terraform plan  -var="project_id=YOUR_PROJECT"
#   terraform apply -var="project_id=YOUR_PROJECT"
#
# Everything here sits inside the free tier or the trial credit at demo scale.
# =============================================================================

terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# -----------------------------------------------------------------------------
# services
# -----------------------------------------------------------------------------

resource "google_project_service" "required" {
  for_each = toset([
    "aiplatform.googleapis.com",         # Vertex AI, Gemini and Agent Engine
    "run.googleapis.com",                # tool server, webhooks, web app
    "firestore.googleapis.com",          # run state, drives the live UI
    "storage.googleapis.com",            # scripts, evidence pages, reports
    "bigquery.googleapis.com",           # cost telemetry, eval, precedent corpus
    "pubsub.googleapis.com",             # research queue and alert fan out
    "cloudtasks.googleapis.com",         # retry and backoff
    "cloudscheduler.googleapis.com",     # stale run sweep
    "secretmanager.googleapis.com",      # the Parallel key, never an env var
    "logging.googleapis.com",            # adjudication audit trail
    "cloudtrace.googleapis.com",         # per stage spans
    "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com",
  ])

  service            = each.value
  disable_on_destroy = false
}

# -----------------------------------------------------------------------------
# firestore
# -----------------------------------------------------------------------------

resource "google_firestore_database" "main" {
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  # A clearance record is evidence. Recovering a deleted one is not optional.
  point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_ENABLED"
  delete_protection_state           = "DELETE_PROTECTION_ENABLED"

  depends_on = [google_project_service.required]
}

# NOTE: per project isolation lives in the Firestore security rules, which
# Terraform does not manage. They are written in `FIRESTORE_RULES` in
# src/truestory/api/security.py and deployed with:
#   firebase deploy --only firestore:rules
# An authorisation check that exists only in application code is one deploy
# away from being bypassed, so this step is not optional. README TODO item 5.

# -----------------------------------------------------------------------------
# storage
# -----------------------------------------------------------------------------

resource "google_storage_bucket" "scripts" {
  name                        = "${var.project_id}-truestory-scripts"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  versioning { enabled = true }

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket" "evidence" {
  name                        = "${var.project_id}-truestory-evidence"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  versioning { enabled = true }

  # Seven years, matching the tail on a claims made errors and omissions
  # policy. A claim arriving in year six needs the evidence the production
  # relied on in year one, captured at the moment it was read.
  lifecycle_rule {
    condition {
      age = var.evidence_retention_days
    }
    action {
      type          = "SetStorageClass"
      storage_class = "ARCHIVE"
    }
  }
}

resource "google_storage_bucket" "reports" {
  name                        = "${var.project_id}-truestory-reports"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false
}

resource "google_storage_bucket" "agent_staging" {
  name                        = "${var.project_id}-truestory-staging"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true

  lifecycle_rule {
    condition { age = 30 }
    action { type = "Delete" }
  }
}

# -----------------------------------------------------------------------------
# bigquery
# -----------------------------------------------------------------------------

resource "google_bigquery_dataset" "truestory" {
  dataset_id  = "truestory"
  location    = var.bq_location
  description = "Cost telemetry, evaluation results, and the precedent corpus."

  depends_on = [google_project_service.required]
}

resource "google_bigquery_table" "cost_telemetry" {
  dataset_id          = google_bigquery_dataset.truestory.dataset_id
  table_id            = "cost_telemetry"
  deletion_protection = false

  description = "One row per Evidence record. Every unit economics figure quoted about this system is a query against this table rather than an estimate."

  time_partitioning {
    type  = "DAY"
    field = "retrieved_at"
  }
  clustering = ["provider", "risk_tier"]

  schema = file("${path.module}/schemas/cost_telemetry.json")
}

resource "google_bigquery_table" "eval_results" {
  dataset_id          = google_bigquery_dataset.truestory.dataset_id
  table_id            = "eval_results"
  deletion_protection = false

  description = "Litigation Set and labelled script results, versioned by rubric so a rubric change shows up as a measured change rather than a claim."

  schema = file("${path.module}/schemas/eval_results.json")
}

resource "google_bigquery_table" "precedent_corpus" {
  dataset_id          = google_bigquery_dataset.truestory.dataset_id
  table_id            = "precedent_corpus"
  deletion_protection = false

  description = "Past adjudications with embeddings. Vector search over this is precedent retrieval, and it is the asset that compounds with use."

  schema = file("${path.module}/schemas/precedent_corpus.json")
}

# -----------------------------------------------------------------------------
# async plane
# -----------------------------------------------------------------------------

resource "google_pubsub_topic" "research" {
  name       = "truestory-research"
  depends_on = [google_project_service.required]
}

resource "google_pubsub_topic" "alerts" {
  name = "truestory-alerts"
}

resource "google_pubsub_topic" "dead_letter" {
  name = "truestory-dead-letter"
}

resource "google_pubsub_subscription" "research" {
  name  = "truestory-research-sub"
  topic = google_pubsub_topic.research.id

  ack_deadline_seconds       = 600 # deep research takes minutes
  message_retention_duration = "604800s"

  # A subject that fails five times is a subject a human should look at, not
  # one that retries silently until the report is quietly incomplete.
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter.id
    max_delivery_attempts = 5
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
}

resource "google_cloud_tasks_queue" "retry" {
  name     = "truestory-retry"
  location = var.region

  rate_limits {
    max_dispatches_per_second = 20
    max_concurrent_dispatches = 32
  }

  retry_config {
    max_attempts       = 3
    min_backoff        = "2s"
    max_backoff        = "30s"
    max_doublings      = 3
  }

  depends_on = [google_project_service.required]
}

# The rescue path. A webhook that never lands would otherwise leave a subject
# pending forever and a report quietly incomplete.
resource "google_cloud_scheduler_job" "stale_sweep" {
  name        = "truestory-stale-sweep"
  description = "Poll subjects still pending beyond their tier SLA, then escalate honestly."
  schedule    = "*/15 * * * *"
  time_zone   = "Etc/UTC"
  region      = var.region

  http_target {
    http_method = "POST"
    uri         = "${var.webhook_service_url}/internal/sweep"

    oidc_token {
      service_account_email = google_service_account.pipeline.email
    }
  }

  depends_on = [google_project_service.required]
}

# -----------------------------------------------------------------------------
# secrets
# -----------------------------------------------------------------------------
# Values are never in Terraform state. Add them once by hand:
#   echo -n "KEY" | gcloud secrets versions add truestory-parallel-api-key --data-file=-

resource "google_secret_manager_secret" "parallel_api_key" {
  secret_id = "truestory-parallel-api-key"
  replication { auto {} }
  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret" "webhook_secret" {
  secret_id = "truestory-parallel-webhook-secret"
  replication { auto {} }
}

resource "google_secret_manager_secret" "internal_token" {
  secret_id = "truestory-api-internal-token"
  replication { auto {} }
}
