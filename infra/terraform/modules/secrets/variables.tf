# =============================================================================
# Secrets Module - Variables
# =============================================================================

variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "secrets" {
  description = "Map of secret names to values"
  type        = map(string)
  sensitive   = true
}

variable "cloud_run_sa_email" {
  description = "Email of the Cloud Run service account"
  type        = string
}

variable "parsing_sa_email" {
  description = "Email of the parsing service account"
  type        = string
}
