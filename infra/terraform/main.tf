# =============================================================================
# CAG Production Infrastructure - Main Configuration
# =============================================================================
#
# This Terraform configuration provisions the complete GCP infrastructure for
# the CAG Interactive Gateway production deployment.
#
# Architecture:
# - Cloud Run: API + Frontend (scale-to-zero)
# - Compute Engine: Parsing pipeline (spot instance)
# - Cloud Storage: PDFs and processed data
# - Secret Manager: API keys and credentials
# - Artifact Registry: Docker images
#
# Usage:
#   terraform init
#   terraform plan -var-file=environments/prod.tfvars
#   terraform apply -var-file=environments/prod.tfvars
#
# =============================================================================

# -----------------------------------------------------------------------------
# Enable Required APIs
# -----------------------------------------------------------------------------

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "compute.googleapis.com",
    "storage.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "aiplatform.googleapis.com",
    "iam.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# -----------------------------------------------------------------------------
# Service Accounts
# -----------------------------------------------------------------------------

# Cloud Run service account
resource "google_service_account" "cloud_run" {
  account_id   = "cag-api-sa"
  display_name = "CAG API Service Account"
  description  = "Service account for Cloud Run API service"
}

# Parsing VM service account
resource "google_service_account" "parsing" {
  account_id   = "cag-parsing-sa"
  display_name = "CAG Parsing Service Account"
  description  = "Service account for parsing pipeline VM"
}

# -----------------------------------------------------------------------------
# IAM Bindings
# -----------------------------------------------------------------------------

# Cloud Run permissions
resource "google_project_iam_member" "cloud_run_permissions" {
  for_each = toset([
    "roles/storage.objectViewer",
    "roles/secretmanager.secretAccessor",
    "roles/aiplatform.user",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.cloud_run.email}"
}

# Parsing VM permissions
resource "google_project_iam_member" "parsing_permissions" {
  for_each = toset([
    "roles/storage.objectAdmin",
    "roles/secretmanager.secretAccessor",
    "roles/aiplatform.user",
    "roles/artifactregistry.reader",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.parsing.email}"
}

# -----------------------------------------------------------------------------
# Storage Module
# -----------------------------------------------------------------------------

module "storage" {
  source = "./modules/storage"

  project_id  = var.project_id
  region      = var.region
  bucket_name = "cag-data-${var.project_id}"

  depends_on = [google_project_service.apis]
}

# -----------------------------------------------------------------------------
# Secrets Module
# -----------------------------------------------------------------------------

module "secrets" {
  source = "./modules/secrets"

  project_id = var.project_id

  secret_names = [
    "qdrant-url",
    "qdrant-api-key",
    "cohere-api-key",
    "google-api-key",
    "posthog-key",
    "access-code",
  ]

  secret_values = {
    "qdrant-url"     = var.qdrant_url
    "qdrant-api-key" = var.qdrant_api_key
    "cohere-api-key" = var.cohere_api_key
    "google-api-key" = var.google_api_key
    "posthog-key"    = var.posthog_key
    "access-code"    = var.access_code
  }

  cloud_run_sa_email = google_service_account.cloud_run.email
  parsing_sa_email   = google_service_account.parsing.email

  depends_on = [google_project_service.apis]
}

# -----------------------------------------------------------------------------
# Artifact Registry
# -----------------------------------------------------------------------------

resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = "cag-images"
  description   = "Docker images for CAG application"
  format        = "DOCKER"

  depends_on = [google_project_service.apis]
}

# -----------------------------------------------------------------------------
# Cloud Run Module
# -----------------------------------------------------------------------------

module "cloud_run" {
  source = "./modules/cloud_run"

  project_id   = var.project_id
  region       = var.region
  service_name = "cag-api"

  # Image will be set by CI/CD, use placeholder for initial apply
  image = var.api_image != "" ? var.api_image : "${var.region}-docker.pkg.dev/${var.project_id}/cag-images/cag-api:latest"

  memory        = var.api_memory
  cpu           = var.api_cpu
  min_instances = var.api_min_instances
  max_instances = var.api_max_instances

  service_account_email = google_service_account.cloud_run.email

  env_vars = {
    ENVIRONMENT           = var.environment
    DATA_BUCKET           = module.storage.bucket_name
    USE_VERTEX_AI         = "true"
    USE_VERTEX_EMBEDDINGS = "true"
    GOOGLE_CLOUD_PROJECT  = var.project_id
    VERTEX_AI_REGION      = var.region
    LLM_PROVIDER          = "gemini"
  }

  secret_env_vars = {
    QDRANT_URL     = module.secrets.secret_ids["qdrant-url"]
    QDRANT_API_KEY = module.secrets.secret_ids["qdrant-api-key"]
    COHERE_API_KEY = module.secrets.secret_ids["cohere-api-key"]
    GOOGLE_API_KEY = module.secrets.secret_ids["google-api-key"]
  }

  depends_on = [
    google_project_service.apis,
    module.storage,
    module.secrets,
    google_artifact_registry_repository.images,
  ]
}

# -----------------------------------------------------------------------------
# Compute Engine Module (Parsing VM)
# -----------------------------------------------------------------------------

module "compute" {
  source = "./modules/compute"

  project_id    = var.project_id
  region        = var.region
  zone          = var.zone
  instance_name = "cag-parsing-vm"

  machine_type  = var.parsing_machine_type
  disk_size_gb  = var.parsing_disk_size
  preemptible   = var.parsing_preemptible

  # GPU configuration for faster Docling processing
  enable_gpu = var.parsing_enable_gpu
  gpu_type   = var.parsing_gpu_type
  gpu_count  = var.parsing_gpu_count

  service_account_email = google_service_account.parsing.email

  data_bucket = module.storage.bucket_name

  labels = {
    app         = "cag"
    component   = "parsing"
    environment = var.environment
  }

  depends_on = [
    google_project_service.apis,
    module.storage,
    module.secrets,
  ]
}
