variable "project_id" {
  description = "Billed Google Cloud project with the four console-managed secrets."
  type        = string
  default     = "go-all-electric-demo"
}

variable "region" {
  type    = string
  default = "europe-west2"
}

variable "service_name" {
  type    = string
  default = "go-all-electric"
}

variable "image" {
  description = "Built Artifact Registry image reference. Null bootstraps infrastructure without a service. Keep the deployed reference in your private tfvars for subsequent plans."
  type        = string
  default     = null
  nullable    = true
  validation {
    condition     = var.image == null ? true : length(trimspace(var.image)) > 0
    error_message = "image must be null for bootstrap or a non-empty built image reference."
  }
}

variable "gemini_requests_per_ip" {
  type    = number
  default = 300
  validation {
    condition     = var.gemini_requests_per_ip >= 0 && floor(var.gemini_requests_per_ip) == var.gemini_requests_per_ip
    error_message = "gemini_requests_per_ip must be a non-negative integer (0 disables the limit)."
  }
}

variable "gemini_limit_window_seconds" {
  type    = number
  default = 3600
  validation {
    condition     = var.gemini_limit_window_seconds > 0 && floor(var.gemini_limit_window_seconds) == var.gemini_limit_window_seconds
    error_message = "gemini_limit_window_seconds must be a positive integer."
  }
}
