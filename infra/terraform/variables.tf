# =============================================================================
# CAG Production Infrastructure - Input Variables
# =============================================================================

# -----------------------------------------------------------------------------
# Project Configuration
# -----------------------------------------------------------------------------

variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP region for resources"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "GCP zone for zonal resources"
  type        = string
  default     = "us-central1-a"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "prod"
}

# -----------------------------------------------------------------------------
# Cloud Run Configuration
# -----------------------------------------------------------------------------

variable "api_image" {
  description = "Docker image for API service (will be set by CI/CD)"
  type        = string
  default     = ""
}

variable "api_min_instances" {
  description = "Minimum Cloud Run instances (0 for scale-to-zero)"
  type        = number
  default     = 0
}

variable "api_max_instances" {
  description = "Maximum Cloud Run instances"
  type        = number
  default     = 5
}

variable "api_memory" {
  description = "Memory allocation for Cloud Run"
  type        = string
  default     = "2Gi"
}

variable "api_cpu" {
  description = "CPU allocation for Cloud Run"
  type        = string
  default     = "2"
}

# -----------------------------------------------------------------------------
# Compute Engine Configuration (Parsing VM)
# -----------------------------------------------------------------------------

variable "parsing_machine_type" {
  description = "Machine type for parsing VM"
  type        = string
  default     = "e2-standard-4" # 4 vCPU, 16GB RAM
}

variable "parsing_disk_size" {
  description = "Boot disk size in GB for parsing VM"
  type        = number
  default     = 100
}

variable "parsing_preemptible" {
  description = "Use preemptible/spot instances for cost savings"
  type        = bool
  default     = true
}

# -----------------------------------------------------------------------------
# External Services
# -----------------------------------------------------------------------------

variable "qdrant_url" {
  description = "Qdrant Cloud cluster URL"
  type        = string
  sensitive   = true
}

variable "qdrant_api_key" {
  description = "Qdrant Cloud API key"
  type        = string
  sensitive   = true
}

variable "cohere_api_key" {
  description = "Cohere API key for reranking"
  type        = string
  sensitive   = true
}

variable "google_api_key" {
  description = "Google API key for Gemini"
  type        = string
  sensitive   = true
}

# -----------------------------------------------------------------------------
# Frontend Configuration
# -----------------------------------------------------------------------------

variable "posthog_key" {
  description = "PostHog analytics key"
  type        = string
  default     = ""
  sensitive   = true
}

variable "access_code" {
  description = "Frontend access gate code"
  type        = string
  default     = "cag-prod-2025"
  sensitive   = true
}

# -----------------------------------------------------------------------------
# Monitoring
# -----------------------------------------------------------------------------

variable "alert_email" {
  description = "Email for monitoring alerts"
  type        = string
  default     = ""
}
