# =============================================================================
# Secrets Module - Secret Manager
# =============================================================================

# Create secrets
resource "google_secret_manager_secret" "secrets" {
  for_each = var.secrets

  secret_id = each.key
  project   = var.project_id

  replication {
    auto {}
  }

  labels = {
    app        = "cag"
    managed_by = "terraform"
  }
}

# Create secret versions
resource "google_secret_manager_secret_version" "versions" {
  for_each = var.secrets

  secret      = google_secret_manager_secret.secrets[each.key].id
  secret_data = each.value
}

# Grant Cloud Run access to secrets
resource "google_secret_manager_secret_iam_member" "cloud_run_access" {
  for_each = var.secrets

  secret_id = google_secret_manager_secret.secrets[each.key].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.cloud_run_sa_email}"
}

# Grant Parsing VM access to secrets
resource "google_secret_manager_secret_iam_member" "parsing_access" {
  for_each = var.secrets

  secret_id = google_secret_manager_secret.secrets[each.key].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.parsing_sa_email}"
}
