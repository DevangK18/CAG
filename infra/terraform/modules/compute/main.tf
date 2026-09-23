# =============================================================================
# Compute Module - Parsing VM
# =============================================================================

# Startup script for parsing VM
locals {
  # Base startup script (common to CPU and GPU)
  base_startup = <<-EOF
    #!/bin/bash
    set -e

    # Install Docker
    if ! command -v docker &> /dev/null; then
      curl -fsSL https://get.docker.com -o get-docker.sh
      sh get-docker.sh
      usermod -aG docker $(whoami)
    fi

    # Install Docker Compose
    if ! command -v docker-compose &> /dev/null; then
      curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
      chmod +x /usr/local/bin/docker-compose
    fi

    # Install gcloud CLI (if not present)
    if ! command -v gcloud &> /dev/null; then
      curl https://sdk.cloud.google.com | bash -s -- --disable-prompts
    fi

    # Create app directory
    mkdir -p /app/data/{raw,processed}/{union,state,local_body}
    mkdir -p /app/logs

    # Set environment variables
    echo "DATA_BUCKET=${var.data_bucket}" >> /etc/environment
    echo "GOOGLE_CLOUD_PROJECT=$(curl -s http://metadata.google.internal/computeMetadata/v1/project/project-id -H 'Metadata-Flavor: Google')" >> /etc/environment

    # Configure Docker to use Artifact Registry
    gcloud auth configure-docker ${var.region}-docker.pkg.dev --quiet
  EOF

  # GPU-specific setup (NVIDIA drivers + Container Toolkit)
  gpu_startup = <<-EOF

    # Install NVIDIA drivers and Container Toolkit for GPU support
    echo "Installing NVIDIA drivers..."

    # Install NVIDIA driver (if not already installed)
    if ! command -v nvidia-smi &> /dev/null; then
      # Add NVIDIA package repositories
      curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
      curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
        tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

      apt-get update

      # Install NVIDIA driver (headless for servers)
      apt-get install -y linux-headers-$(uname -r)
      apt-get install -y nvidia-driver-535-server

      # Install NVIDIA Container Toolkit
      apt-get install -y nvidia-container-toolkit

      # Configure Docker to use NVIDIA runtime
      nvidia-ctk runtime configure --runtime=docker
      systemctl restart docker

      echo "NVIDIA drivers installed. Reboot may be required."
    else
      echo "NVIDIA drivers already installed: $(nvidia-smi --query-gpu=driver_version --format=csv,noheader)"
    fi
  EOF

  # Combine scripts based on GPU configuration
  startup_script = var.enable_gpu ? "${local.base_startup}${local.gpu_startup}\n\necho 'Parsing VM startup complete (GPU enabled)'" : "${local.base_startup}\n\necho 'Parsing VM startup complete'"
}

resource "google_compute_instance" "parsing" {
  name         = var.instance_name
  machine_type = var.machine_type
  zone         = var.zone
  project      = var.project_id

  # Standard by default (spot preemptions killed long parsing runs); spot optional
  scheduling {
    preemptible        = var.preemptible
    provisioning_model = var.preemptible ? "SPOT" : "STANDARD"
    automatic_restart  = !var.preemptible

    # Standard e2 VMs require MIGRATE; spot and GPU VMs require TERMINATE
    on_host_maintenance = (var.preemptible || var.enable_gpu) ? "TERMINATE" : "MIGRATE"
  }

  # GPU accelerator (optional, for faster Docling processing)
  dynamic "guest_accelerator" {
    for_each = var.enable_gpu ? [1] : []
    content {
      type  = var.gpu_type
      count = var.gpu_count
    }
  }

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = var.disk_size_gb
      type  = "pd-ssd"
    }
  }

  network_interface {
    network = "default"

    # Ephemeral external IP for egress
    access_config {}
  }

  service_account {
    email  = var.service_account_email
    scopes = ["cloud-platform"]
  }

  metadata = {
    startup-script = local.startup_script
  }

  labels = var.labels

  tags = ["cag-parsing", "allow-ssh"]

  # Allow the instance to be stopped manually (cost saving)
  allow_stopping_for_update = true
}

# Firewall rule for SSH access via IAP
resource "google_compute_firewall" "allow_iap_ssh" {
  name    = "allow-iap-ssh-parsing"
  network = "default"
  project = var.project_id

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  # IAP's IP range
  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["cag-parsing"]
}
