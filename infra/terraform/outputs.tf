# =============================================================================
# CAG Production Infrastructure - Outputs
# =============================================================================

# -----------------------------------------------------------------------------
# Cloud Run Outputs
# -----------------------------------------------------------------------------

output "api_url" {
  description = "URL of the Cloud Run API service"
  value       = module.cloud_run.service_url
}

output "api_service_name" {
  description = "Name of the Cloud Run service"
  value       = module.cloud_run.service_name
}

# -----------------------------------------------------------------------------
# Storage Outputs
# -----------------------------------------------------------------------------

output "data_bucket_name" {
  description = "Name of the Cloud Storage bucket for data"
  value       = module.storage.bucket_name
}

output "data_bucket_url" {
  description = "URL of the Cloud Storage bucket"
  value       = module.storage.bucket_url
}

# -----------------------------------------------------------------------------
# Compute Engine Outputs
# -----------------------------------------------------------------------------

output "parsing_vm_name" {
  description = "Name of the parsing VM"
  value       = module.compute.instance_name
}

output "parsing_vm_zone" {
  description = "Zone of the parsing VM"
  value       = module.compute.zone
}

output "parsing_vm_internal_ip" {
  description = "Internal IP of the parsing VM"
  value       = module.compute.internal_ip
}

# -----------------------------------------------------------------------------
# Artifact Registry Outputs
# -----------------------------------------------------------------------------

output "artifact_registry_url" {
  description = "URL for pushing Docker images"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/cag-images"
}

# -----------------------------------------------------------------------------
# Service Account Outputs
# -----------------------------------------------------------------------------

output "cloud_run_sa_email" {
  description = "Email of the Cloud Run service account"
  value       = google_service_account.cloud_run.email
}

output "parsing_sa_email" {
  description = "Email of the parsing service account"
  value       = google_service_account.parsing.email
}

# -----------------------------------------------------------------------------
# Quick Reference
# -----------------------------------------------------------------------------

output "quick_reference" {
  description = "Quick reference commands"
  value       = <<-EOT

    ============================================================
    CAG Production Deployment - Quick Reference
    ============================================================

    API URL: ${module.cloud_run.service_url}

    Push Docker Image:
      docker tag cag-api ${var.region}-docker.pkg.dev/${var.project_id}/cag-images/cag-api:latest
      docker push ${var.region}-docker.pkg.dev/${var.project_id}/cag-images/cag-api:latest

    Start Parsing VM:
      gcloud compute instances start ${module.compute.instance_name} --zone=${module.compute.zone}

    SSH to Parsing VM:
      gcloud compute ssh ${module.compute.instance_name} --zone=${module.compute.zone}

    Stop Parsing VM (save costs):
      gcloud compute instances stop ${module.compute.instance_name} --zone=${module.compute.zone}

    View Logs:
      gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=cag-api" --limit=50

    Upload Manifest:
      gsutil cp manifest.xlsx gs://${module.storage.bucket_name}/manifests/

    ============================================================
  EOT
}
