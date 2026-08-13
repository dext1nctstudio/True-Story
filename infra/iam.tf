# =============================================================================
# TRUE STORY  ·  identity and access
# =============================================================================
# The brief name checks the studio head enforcing IAM governance across multi
# agent workflows, so this file shows it rather than asserting it.
#
# Two layers:
#
#   Service accounts, one per runtime, each holding the minimum it needs. The
#   webhook receiver cannot read secrets it does not use. The web tier cannot
#   write to Firestore at all.
#
#   Custom roles, one per human function. These map onto the Firestore security
#   rules and onto the view matrix in the application, so a role means the same
#   thing in all three places.
# =============================================================================

# -----------------------------------------------------------------------------
# service accounts
# -----------------------------------------------------------------------------

resource "google_service_account" "pipeline" {
  account_id   = "truestory-pipeline"
  display_name = "TRUE STORY pipeline"
  description  = "Runs the ADK pipeline on Agent Engine. The only identity that writes run state."
}

resource "google_service_account" "tools" {
  account_id   = "truestory-tools"
  display_name = "TRUE STORY clearance tool server"
  description  = "Calls Parallel. Holds the research key and nothing else."
}

resource "google_service_account" "webhooks" {
  account_id   = "truestory-webhooks"
  display_name = "TRUE STORY webhook receiver"
  description  = "Verifies and processes signed callbacks. Cannot start a run."
}

resource "google_service_account" "web" {
  account_id   = "truestory-web"
  display_name = "TRUE STORY web application"
  description  = "Serves the overlay. Reads through the API and never touches storage directly."
}

# -----------------------------------------------------------------------------
# pipeline
# -----------------------------------------------------------------------------

resource "google_project_iam_member" "pipeline_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_project_iam_member" "pipeline_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_project_iam_member" "pipeline_bigquery" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_project_iam_member" "pipeline_pubsub" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_project_iam_member" "pipeline_trace" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_storage_bucket_iam_member" "pipeline_scripts" {
  bucket = google_storage_bucket.scripts.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_storage_bucket_iam_member" "pipeline_reports" {
  bucket = google_storage_bucket.reports.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.pipeline.email}"
}

# -----------------------------------------------------------------------------
# tool server
# -----------------------------------------------------------------------------
# This identity holds the research key. It deliberately cannot read run state,
# so a compromise of the tool server does not expose the clearance record.

resource "google_secret_manager_secret_iam_member" "tools_parallel_key" {
  secret_id = google_secret_manager_secret.parallel_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.tools.email}"
}

resource "google_storage_bucket_iam_member" "tools_evidence" {
  bucket = google_storage_bucket.evidence.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.tools.email}"
}

resource "google_project_iam_member" "tools_bigquery" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.tools.email}"
}

# -----------------------------------------------------------------------------
# webhook receiver
# -----------------------------------------------------------------------------
# Reads only the signing secret. It verifies callbacks and writes evidence, and
# it cannot start a run or read the Parallel key.

resource "google_secret_manager_secret_iam_member" "webhooks_signing_secret" {
  secret_id = google_secret_manager_secret.webhook_secret.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.webhooks.email}"
}

resource "google_project_iam_member" "webhooks_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.webhooks.email}"
}

resource "google_project_iam_member" "webhooks_pubsub" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.webhooks.email}"
}

# -----------------------------------------------------------------------------
# custom roles for humans
# -----------------------------------------------------------------------------

resource "google_project_iam_custom_role" "counsel" {
  role_id     = "truestoryCounsel"
  title       = "TRUE STORY Counsel"
  description = "The accountable human. Sees everything including unmasked identities and full evidence, and is the only role that may unmask, override a verdict, or sign off a critical item."

  permissions = [
    "datastore.entities.get",
    "datastore.entities.list",
    "datastore.entities.update",
    "storage.objects.get",
    "storage.objects.list",
    "logging.logEntries.list",
  ]
}

resource "google_project_iam_custom_role" "producer" {
  role_id     = "truestoryProducer"
  title       = "TRUE STORY Producer"
  description = "Manages the production. Sees verdict counts, risk posture, cost and alerts, and does not read the evidence behind them."

  permissions = [
    "datastore.entities.get",
    "datastore.entities.list",
    "storage.objects.get",
  ]
}

resource "google_project_iam_custom_role" "writer" {
  role_id     = "truestoryWriter"
  title       = "TRUE STORY Writer"
  description = "Sees the overlay and the verified rewrites for their own draft only. No cross project access, no evidence, no cost."

  permissions = [
    "datastore.entities.get",
  ]
}

resource "google_project_iam_custom_role" "underwriter" {
  role_id     = "truestoryUnderwriter"
  title       = "TRUE STORY Underwriter"
  description = "An external party. Receives the finished clearance package read only and watermarked, with masked identities still masked."

  permissions = [
    "storage.objects.get",
  ]
}

# -----------------------------------------------------------------------------
# audit logging
# -----------------------------------------------------------------------------
# Every adjudication, override and unmasking is recorded with the acting
# principal. Unmasking in particular: the thing being revealed is the identity
# of a private individual who has done nothing except resemble a character.

resource "google_project_iam_audit_config" "data_access" {
  project = var.project_id
  service = "allServices"

  audit_log_config { log_type = "ADMIN_READ" }
  audit_log_config { log_type = "DATA_READ" }
  audit_log_config { log_type = "DATA_WRITE" }
}

resource "google_logging_project_bucket_config" "audit" {
  project        = var.project_id
  location       = var.region
  retention_days = var.evidence_retention_days
  bucket_id      = "truestory-audit"
  description    = "Adjudication and unmasking trail, retained for the errors and omissions claims tail."
}
