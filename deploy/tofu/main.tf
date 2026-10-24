locals {
  secret_names = toset([
    "GEMINI_API_KEY", "MONGODB_URI", "EPC_API_TOKEN", "ACCESS_CODE_HASH", "SESSION_SECRET",
  ])
  required_apis = toset([
    "run.googleapis.com", "cloudbuild.googleapis.com", "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com", "iam.googleapis.com", "logging.googleapis.com",
    "compute.googleapis.com", "cloudresourcemanager.googleapis.com", "storage.googleapis.com",
  ])
}

# Metadata only. No dependency on API resources: missing/inaccessible secrets fail
# during plan, including bootstrap, with the secret name and API error. Create
# these five secrets in the console and enable Secret Manager before planning.
data "google_secret_manager_secret" "existing" {
  for_each  = local.secret_names
  project   = var.project_id
  secret_id = each.value
}

resource "google_project_service" "required" {
  for_each           = local.required_apis
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_compute_network" "egress" {
  name                    = "gae-network"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.required]
}

resource "google_compute_subnetwork" "egress" {
  name          = "gae-egress"
  ip_cidr_range = "10.42.0.0/24"
  region        = var.region
  network       = google_compute_network.egress.id
}

resource "google_compute_router" "egress" {
  name    = "gae-router"
  region  = var.region
  network = google_compute_network.egress.id
}

resource "google_compute_address" "egress" {
  name         = "gae-egress-ip"
  region       = var.region
  address_type = "EXTERNAL"
  depends_on   = [google_project_service.required]
}

resource "google_compute_router_nat" "egress" {
  name                               = "gae-nat"
  router                             = google_compute_router.egress.name
  region                             = var.region
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = [google_compute_address.egress.self_link]
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"
  subnetwork {
    name                    = google_compute_subnetwork.egress.id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }
}

resource "google_service_account" "runtime" {
  account_id   = "gae-runtime"
  display_name = "Go All-Electric runtime"
  depends_on   = [google_project_service.required]
}

resource "google_service_account" "build" {
  account_id   = "gae-build"
  display_name = "Go All-Electric image builder"
  depends_on   = [google_project_service.required]
}

resource "google_project_iam_member" "build" {
  project = var.project_id
  role    = "roles/run.builder"
  member  = "serviceAccount:${google_service_account.build.email}"
}

resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = "go-all-electric"
  format        = "DOCKER"
  depends_on    = [google_project_service.required]
}

resource "google_secret_manager_secret_iam_member" "runtime" {
  for_each  = local.secret_names
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.existing[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

# This resource manages exclusions on the existing _Default sink, without
# taking ownership of that sink or replacing its unrelated exclusions.
resource "google_logging_project_exclusion" "requests" {
  project     = var.project_id
  name        = "${var.service_name}-requests"
  description = "Do not store request URLs containing postcodes."
  disabled    = false
  filter      = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.service_name}\" AND log_id(\"run.googleapis.com/requests\")"
  depends_on  = [google_project_service.required]
}

resource "google_cloud_run_v2_service" "app" {
  count               = var.image == null ? 0 : 1
  name                = var.service_name
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account                  = google_service_account.runtime.email
    timeout                          = "900s"
    max_instance_request_concurrency = 8
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    vpc_access {
      egress = "ALL_TRAFFIC"
      network_interfaces {
        network    = google_compute_network.egress.name
        subnetwork = google_compute_subnetwork.egress.name
      }
    }
    containers {
      image = var.image
      resources {
        limits = {
          cpu    = "1"
          memory = "2Gi"
        }
      }
      dynamic "env" {
        for_each = local.secret_names
        content {
          name = env.value
          value_source {
            secret_key_ref {
              secret  = data.google_secret_manager_secret.existing[env.value].secret_id
              version = "latest"
            }
          }
        }
      }
      env {
        name  = "GEMINI_REQUESTS_PER_IP"
        value = tostring(var.gemini_requests_per_ip)
      }
      env {
        name  = "GEMINI_LIMIT_WINDOW_SECONDS"
        value = tostring(var.gemini_limit_window_seconds)
      }
    }
  }

  # Establish privacy, runtime access and static egress before any revision starts.
  depends_on = [
    google_logging_project_exclusion.requests,
    google_secret_manager_secret_iam_member.runtime,
    google_compute_router_nat.egress,
    google_artifact_registry_repository.images,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  count    = var.image == null ? 0 : 1
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.app[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
