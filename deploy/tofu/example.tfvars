project_id = "go-all-electric-demo"
region     = "europe-west2"
# Leave image null for the first plan/apply. After building, save the printed
# image reference here in your private terraform.tfvars before future plans.
image                       = null
gemini_requests_per_ip      = 300
gemini_limit_window_seconds = 3600
