variable "project_id" {
  type        = string
  description = "Google Cloud project id."
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "Region for Cloud Run, Firestore, Tasks and Scheduler. Keep them together to avoid cross region latency inside a run."
}

variable "bq_location" {
  type        = string
  default     = "US"
  description = "BigQuery dataset location. Multi region is fine for telemetry."
}

variable "evidence_retention_days" {
  type        = number
  default     = 2555
  description = "Seven years. Matches the tail on a claims made errors and omissions policy: a claim arriving in year six needs the evidence relied on in year one."
}

variable "webhook_service_url" {
  type        = string
  default     = ""
  description = "Cloud Run URL of the webhook receiver. Populated after the first deploy, then reapplied so the scheduler can reach the sweep endpoint."
}

variable "min_instances_webhooks" {
  type        = number
  default     = 1
  description = "The receiver must stay warm while the pipeline is idle. Monitor events arrive weeks after the run that created them."
}

variable "min_instances_web" {
  type        = number
  default     = 1
  description = "Keeps the demo URL warm through judging. A cold start on the one link a judge opens is an avoidable loss."
}

variable "budget_per_script_usd" {
  type        = number
  default     = 5.0
  description = "Default research ceiling per script run."
}
