output "service_url" {
  description = "Null until an image is supplied and the service is deployed."
  value       = try(google_cloud_run_v2_service.app[0].uri, null)
}

output "egress_ip" {
  value = google_compute_address.egress.address
}

output "atlas_allowlist_reminder" {
  value = "Allowlist exactly ${google_compute_address.egress.address}/32 in MongoDB Atlas network access. Remove this entry by hand after destroy."
}

output "image_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}
