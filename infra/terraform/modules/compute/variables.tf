# =============================================================================
# Compute Module - Variables
# =============================================================================

variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "zone" {
  description = "GCP zone for the VM"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "instance_name" {
  description = "Name of the Compute Engine instance"
  type        = string
}

variable "machine_type" {
  description = "Machine type for the VM"
  type        = string
  default     = "e2-standard-4"
}

variable "disk_size_gb" {
  description = "Boot disk size in GB"
  type        = number
  default     = 100
}

variable "preemptible" {
  description = "Use preemptible/spot instance"
  type        = bool
  default     = true
}

variable "service_account_email" {
  description = "Service account email for the VM"
  type        = string
}

variable "data_bucket" {
  description = "Cloud Storage bucket for data"
  type        = string
}

variable "labels" {
  description = "Labels for the VM"
  type        = map(string)
  default     = {}
}

variable "enable_gpu" {
  description = "Attach GPU to VM for faster ML inference"
  type        = bool
  default     = false
}

variable "gpu_type" {
  description = "GPU type (e.g., nvidia-tesla-t4)"
  type        = string
  default     = "nvidia-tesla-t4"
}

variable "gpu_count" {
  description = "Number of GPUs to attach"
  type        = number
  default     = 1
}
