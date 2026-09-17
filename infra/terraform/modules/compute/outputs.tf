# =============================================================================
# Compute Module - Outputs
# =============================================================================

output "instance_name" {
  description = "Name of the Compute Engine instance"
  value       = google_compute_instance.parsing.name
}

output "zone" {
  description = "Zone of the instance"
  value       = google_compute_instance.parsing.zone
}

output "internal_ip" {
  description = "Internal IP address"
  value       = google_compute_instance.parsing.network_interface[0].network_ip
}

output "external_ip" {
  description = "External IP address"
  value       = google_compute_instance.parsing.network_interface[0].access_config[0].nat_ip
}

output "instance_id" {
  description = "Instance ID"
  value       = google_compute_instance.parsing.instance_id
}
