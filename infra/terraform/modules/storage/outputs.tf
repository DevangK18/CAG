# =============================================================================
# Storage Module - Outputs
# =============================================================================

output "bucket_name" {
  description = "Name of the created bucket"
  value       = google_storage_bucket.data.name
}

output "bucket_url" {
  description = "URL of the created bucket"
  value       = google_storage_bucket.data.url
}

output "bucket_self_link" {
  description = "Self-link of the created bucket"
  value       = google_storage_bucket.data.self_link
}
