#!/bin/bash
# =============================================================================
# CAG GCP Project Setup Script
# =============================================================================
# This script sets up a new GCP project for the CAG application.
# Run this once before running Terraform.
#
# Usage:
#   ./setup-gcp.sh <project-id>
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - Billing account linked to GCP project
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check arguments
if [ -z "$1" ]; then
    echo -e "${RED}Error: Project ID required${NC}"
    echo "Usage: $0 <project-id>"
    exit 1
fi

PROJECT_ID=$1
REGION=${2:-us-central1}

echo -e "${GREEN}Setting up GCP project: ${PROJECT_ID}${NC}"
echo "Region: ${REGION}"
echo ""

# Set the project
echo -e "${YELLOW}Setting active project...${NC}"
gcloud config set project ${PROJECT_ID}

# Enable required APIs
echo -e "${YELLOW}Enabling required APIs...${NC}"
APIS=(
    "run.googleapis.com"
    "compute.googleapis.com"
    "storage.googleapis.com"
    "secretmanager.googleapis.com"
    "artifactregistry.googleapis.com"
    "cloudbuild.googleapis.com"
    "aiplatform.googleapis.com"
    "iam.googleapis.com"
    "iamcredentials.googleapis.com"
)

for api in "${APIS[@]}"; do
    echo "  Enabling ${api}..."
    gcloud services enable ${api} --quiet
done

# Create Terraform state bucket
STATE_BUCKET="cag-terraform-state-${PROJECT_ID}"
echo -e "${YELLOW}Creating Terraform state bucket: ${STATE_BUCKET}${NC}"
if gsutil ls -b gs://${STATE_BUCKET} 2>/dev/null; then
    echo "  Bucket already exists"
else
    gsutil mb -l ${REGION} gs://${STATE_BUCKET}
    gsutil versioning set on gs://${STATE_BUCKET}
fi

# Set up Workload Identity Federation for GitHub Actions
echo -e "${YELLOW}Setting up Workload Identity Federation for GitHub Actions...${NC}"

# Create Workload Identity Pool
POOL_NAME="github-pool"
if gcloud iam workload-identity-pools describe ${POOL_NAME} \
    --location="global" --project=${PROJECT_ID} 2>/dev/null; then
    echo "  Workload Identity Pool already exists"
else
    gcloud iam workload-identity-pools create ${POOL_NAME} \
        --location="global" \
        --display-name="GitHub Actions Pool" \
        --project=${PROJECT_ID}
fi

# Create Workload Identity Provider (for GitHub)
PROVIDER_NAME="github-provider"
if gcloud iam workload-identity-pools providers describe ${PROVIDER_NAME} \
    --workload-identity-pool=${POOL_NAME} \
    --location="global" --project=${PROJECT_ID} 2>/dev/null; then
    echo "  Workload Identity Provider already exists"
else
    gcloud iam workload-identity-pools providers create-oidc ${PROVIDER_NAME} \
        --workload-identity-pool=${POOL_NAME} \
        --location="global" \
        --issuer-uri="https://token.actions.githubusercontent.com" \
        --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository" \
        --project=${PROJECT_ID}
fi

# Create service account for GitHub Actions
SA_NAME="github-actions-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

if gcloud iam service-accounts describe ${SA_EMAIL} --project=${PROJECT_ID} 2>/dev/null; then
    echo "  Service account already exists: ${SA_EMAIL}"
else
    echo "  Creating service account: ${SA_EMAIL}"
    gcloud iam service-accounts create ${SA_NAME} \
        --display-name="GitHub Actions Service Account" \
        --project=${PROJECT_ID}
fi

# Grant necessary roles to GitHub Actions SA
echo -e "${YELLOW}Granting roles to GitHub Actions service account...${NC}"
ROLES=(
    "roles/run.developer"
    "roles/storage.admin"
    "roles/artifactregistry.writer"
    "roles/secretmanager.secretAccessor"
    "roles/iam.serviceAccountUser"
    "roles/compute.instanceAdmin.v1"
)

for role in "${ROLES[@]}"; do
    echo "  Granting ${role}..."
    gcloud projects add-iam-policy-binding ${PROJECT_ID} \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="${role}" \
        --quiet
done

# Allow GitHub repository to impersonate the service account
# NOTE: User must update this with their actual GitHub repository
echo ""
echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}IMPORTANT: Update GitHub repository binding${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""
echo "Run this command after replacing YOUR_GITHUB_USERNAME/YOUR_REPO:"
echo ""
echo -e "${GREEN}gcloud iam service-accounts add-iam-policy-binding ${SA_EMAIL} \\
    --project=${PROJECT_ID} \\
    --role=\"roles/iam.workloadIdentityUser\" \\
    --member=\"principalSet://iam.googleapis.com/projects/\$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')/locations/global/workloadIdentityPools/${POOL_NAME}/attribute.repository/YOUR_GITHUB_USERNAME/YOUR_REPO\"${NC}"
echo ""

# Output important values
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Setup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Add these to your GitHub repository secrets:"
echo ""
echo "  GCP_PROJECT_ID: ${PROJECT_ID}"
echo ""
echo "  WIF_PROVIDER: projects/$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')/locations/global/workloadIdentityPools/${POOL_NAME}/providers/${PROVIDER_NAME}"
echo ""
echo "  WIF_SERVICE_ACCOUNT: ${SA_EMAIL}"
echo ""
echo "Terraform state bucket: gs://${STATE_BUCKET}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Copy prod.tfvars.example to prod.tfvars and fill in values"
echo "2. Update the GitHub repository binding (command above)"
echo "3. Run: terraform init"
echo "4. Run: terraform plan -var-file=environments/prod.tfvars"
echo "5. Run: terraform apply -var-file=environments/prod.tfvars"
