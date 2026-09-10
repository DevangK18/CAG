# =============================================================================
# Storage Module - Cloud Storage Bucket
# =============================================================================

resource "google_storage_bucket" "data" {
  name     = var.bucket_name
  location = var.region
  project  = var.project_id

  # Prevent accidental deletion
  force_destroy = false

  # Uniform bucket-level access (recommended)
  uniform_bucket_level_access = true

  # Versioning for data protection
  versioning {
    enabled = true
  }

  # Lifecycle rules for cost optimization
  lifecycle_rule {
    condition {
      age = 90 # Days
      matches_prefix = ["processed/"]
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    condition {
      age = 365 # Days
      matches_prefix = ["raw/"]
    }
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
  }

  # Delete old versions after 30 days
  lifecycle_rule {
    condition {
      num_newer_versions = 3
      with_state         = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    app         = "cag"
    managed_by  = "terraform"
  }
}

# Create folder structure with placeholder objects
resource "google_storage_bucket_object" "folders" {
  for_each = toset([
    "manifests/",
    "raw/union/",
    "raw/state/",
    "raw/local_body/",
    "processed/union/",
    "processed/state/",
    "processed/local_body/",
    "logs/parsing/",
    "logs/traces/",
  ])

  name    = "${each.value}.placeholder"
  content = "Folder placeholder"
  bucket  = google_storage_bucket.data.name
}
