#!/bin/bash
# Create a stand-by GPU parsing VM like cag-parsing-gpu-vm, then stop it.
#
# The GPU workflow tries its VMs in order and runs on the first that starts, so a
# zone that has run out of GPUs does not block a run. Stopped VMs cost only their
# disk (150 GB pd-balanced, about $15/month). The project's GPU quota is one, so
# no other GPU VM may be running while this one is created.
#
# Usage: create-gpu-standby.sh NAME ZONE [l4|t4]
#   create-gpu-standby.sh cag-parsing-gpu-vm-2 us-east4-a l4
#   create-gpu-standby.sh cag-parsing-gpu-vm-t4 us-central1-a t4
set -euo pipefail

NAME="$1"
ZONE="$2"
GPU="${3:-l4}"
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
SA="cag-service@${PROJECT_ID}.iam.gserviceaccount.com"

case "${GPU}" in
  l4) MACHINE=g2-standard-8; ACCEL=nvidia-l4 ;;
  t4) MACHINE=n1-standard-8; ACCEL=nvidia-tesla-t4 ;;
  *) echo "GPU must be l4 or t4"; exit 1 ;;
esac

gcloud compute instances create "${NAME}" \
  --project="${PROJECT_ID}" --zone="${ZONE}" \
  --machine-type="${MACHINE}" --accelerator="type=${ACCEL},count=1" \
  --maintenance-policy=TERMINATE --provisioning-model=STANDARD --restart-on-failure \
  --service-account="${SA}" --scopes=https://www.googleapis.com/auth/cloud-platform \
  --tags=cag-parsing --labels=role=parsing-gpu \
  --metadata=install-nvidia-driver=True \
  --image=common-cu129-ubuntu-2204-nvidia-580-v20260909 --image-project=deeplearning-platform-release \
  --boot-disk-size=150GB --boot-disk-type=pd-balanced --boot-disk-device-name="${NAME}" \
  --shielded-integrity-monitoring --shielded-vtpm --no-shielded-secure-boot

for _ in $(seq 1 15); do
  gcloud compute ssh "${NAME}" --zone="${ZONE}" --project="${PROJECT_ID}" --command="true" --quiet && break
  sleep 20
done
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
gcloud compute scp "${SCRIPT_DIR}/setup-gpu-vm.sh" "${NAME}:/tmp/setup-gpu-vm.sh" --zone="${ZONE}" --project="${PROJECT_ID}"
gcloud compute ssh "${NAME}" --zone="${ZONE}" --project="${PROJECT_ID}" \
  --command="sudo -n bash /tmp/setup-gpu-vm.sh && nvidia-smi --query-gpu=name,driver_version --format=csv,noheader"

gcloud compute instances stop "${NAME}" --zone="${ZONE}" --project="${PROJECT_ID}"
echo "${NAME} (${ZONE}, ${GPU}) created and stopped. Add it to the workflow's 'vms' list."
