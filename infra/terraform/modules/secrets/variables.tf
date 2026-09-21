# =============================================================================
# Secrets Module - Variables
# =============================================================================

variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "secret_names" {
  description = "List of secret names to create"
  type        = list(string)
}

variable "secret_values" {
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
