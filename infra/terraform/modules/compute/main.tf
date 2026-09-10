# =============================================================================
# Compute Module - Parsing VM
# =============================================================================

# Startup script for parsing VM
locals {
  startup_script = <<-EOF
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

    echo "Parsing VM startup complete"
  EOF
}

resource "google_compute_instance" "parsing" {
  name         = var.instance_name
  machine_type = var.machine_type
  zone         = var.zone
  project      = var.project_id

  # Spot/preemptible instance for cost savings
  scheduling {
    preemptible         = var.preemptible
    automatic_restart   = false
    on_host_maintenance = "TERMINATE"

    # Use SPOT provisioning model for better availability
    provisioning_model = var.preemptible ? "SPOT" : "STANDARD"
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
