terraform {
  required_version = ">= 1.13.2, < 2.0.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "7.10.0"
    }
  }
  # Intentionally local state; keep the state and its backups private.
}

provider "google" {
  project = var.project_id
  region  = var.region
}
