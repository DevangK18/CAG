#!/bin/bash
# =============================================================================
# Prepare a GPU parsing VM host (idempotent, safe to re-run)
# =============================================================================
# Expects a Google Deep Learning VM image (e.g. family
# common-cu129-ubuntu-2204-nvidia-580) that already ships the NVIDIA driver and
# NVIDIA Container Toolkit. This script NEVER installs or changes the driver;
# it only adds what the image lacks:
#   - Docker CE (from Docker's apt repo), wired to the NVIDIA runtime
#   - docker-credential-gcr (so the "gcr" credHelper used by the workflows works)
#   - docker socket access for SSH users (GitHub's "runner" user)
#   - no unattended upgrades (a background driver/lib upgrade breaks NVML mid-run)
#
# Run on the VM:  sudo bash setup-gpu-vm.sh
# =============================================================================
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root (sudo bash $0)"; exit 1
fi

echo "== Checking NVIDIA driver"
if ! nvidia-smi >/dev/null 2>&1; then
  echo "ERROR: nvidia-smi failed. Use a DLVM image with the driver preinstalled;"
  echo "       this script deliberately does not install drivers."
  exit 1
fi
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader

echo "== Disabling unattended upgrades"
systemctl disable --now unattended-upgrades.service apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
# Wait for any apt run that was already in progress
while fuser /var/lib/dpkg/lock-frontend /var/lib/apt/lists/lock >/dev/null 2>&1; do
  echo "Waiting for apt lock..."; sleep 5
done
# Pin driver, container toolkit and kernel so a manual 'apt upgrade' cannot break them
apt-mark hold $(dpkg-query -W -f='${Package}\n' | grep -E '^(nvidia-|libnvidia-|linux-(image|modules|headers|gcp)|linux-modules-nvidia)' ) >/dev/null
echo "Held $(apt-mark showhold | wc -l) packages"

echo "== Installing Docker CE"
if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin
fi
docker --version

echo "== Configuring NVIDIA runtime for Docker"
if ! grep -q nvidia /etc/docker/daemon.json 2>/dev/null; then
  nvidia-ctk runtime configure --runtime=docker
fi
systemctl enable docker >/dev/null
systemctl restart docker

echo "== Docker socket access for SSH users"
# Users created by the guest agent (e.g. GitHub's runner) are passwordless sudoers
# already, so opening the socket does not widen access on this single-purpose VM.
mkdir -p /etc/systemd/system/docker.socket.d
cat > /etc/systemd/system/docker.socket.d/override.conf << 'EOF'
[Socket]
SocketMode=0666
EOF
systemctl daemon-reload
systemctl restart docker.socket docker
ls -l /var/run/docker.sock

echo "== Installing docker-credential-gcr"
if ! command -v docker-credential-gcr >/dev/null 2>&1; then
  VER=2.2.1
  curl -fsSL "https://github.com/GoogleCloudPlatform/docker-credential-gcr/releases/download/v${VER}/docker-credential-gcr_linux_amd64-${VER}.tar.gz" \
    | tar xz -C /usr/local/bin docker-credential-gcr
  chmod +x /usr/local/bin/docker-credential-gcr
fi
docker-credential-gcr version

echo "== Smoke test: GPU inside a container"
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi -L

echo "GPU VM host setup complete"
