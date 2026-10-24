project_id = "go-all-electric-demo"
region     = "europe-west2"
# Leave image null for bootstrap. deploy/deploy.sh saves subsequent images in
# image.auto.tfvars, which takes precedence over this value.
image                       = null
gemini_requests_per_ip      = 300
gemini_limit_window_seconds = 3600
