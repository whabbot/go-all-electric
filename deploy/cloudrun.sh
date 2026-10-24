#!/usr/bin/env bash
# Run only after gcloud auth login and selection of a billed Google Cloud project.
set -euo pipefail
set +x
: "${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT to the billed project ID}"
PROJECT="$GOOGLE_CLOUD_PROJECT"
SERVICE="${CLOUD_RUN_SERVICE:-go-all-electric}"
REGION=europe-west2
DEPLOY_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
export PROJECT SERVICE

# Check metadata only, before any changes to the project.
SECRETS=(GEMINI_API_KEY MONGODB_URI EPC_API_TOKEN ACCESS_CODE)
MISSING_SECRETS=()
for NAME in "${SECRETS[@]}"; do
  if ! gcloud secrets describe "$NAME" --project "$PROJECT" --quiet >/dev/null 2>&1; then
    MISSING_SECRETS+=("$NAME")
  fi
done
if (( ${#MISSING_SECRETS[@]} )); then
  printf 'Required secrets missing or unavailable: %s\n' "${MISSING_SECRETS[*]}" >&2
  printf 'Create secrets with these exact names in https://console.cloud.google.com/security/secret-manager?project=%s\n' "$PROJECT" >&2
  exit 1
fi

gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com iam.googleapis.com logging.googleapis.com compute.googleapis.com \
  --project "$PROJECT" --quiet

# Direct VPC egress and Cloud NAT give Atlas one stable allowlist address.
NETWORK=gae-network
SUBNET=gae-egress
ROUTER=gae-router
NAT=gae-nat
if ! gcloud compute networks describe "$NETWORK" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud compute networks create "$NETWORK" --subnet-mode=custom --project "$PROJECT" --quiet
fi
if ! gcloud compute networks subnets describe "$SUBNET" --region "$REGION" \
  --project "$PROJECT" >/dev/null 2>&1; then
  gcloud compute networks subnets create "$SUBNET" --network "$NETWORK" \
    --range 10.42.0.0/24 --region "$REGION" --project "$PROJECT" --quiet
fi
if ! gcloud compute routers describe "$ROUTER" --region "$REGION" \
  --project "$PROJECT" >/dev/null 2>&1; then
  gcloud compute routers create "$ROUTER" --network "$NETWORK" \
    --region "$REGION" --project "$PROJECT" --quiet
fi
if ! gcloud compute addresses describe gae-egress-ip --region "$REGION" \
  --project "$PROJECT" >/dev/null 2>&1; then
  gcloud compute addresses create gae-egress-ip --region "$REGION" --project "$PROJECT" --quiet
fi
if gcloud compute routers nats describe "$NAT" --router "$ROUTER" --region "$REGION" \
  --project "$PROJECT" >/dev/null 2>&1; then
  NAT_ACTION=update
else
  NAT_ACTION=create
fi
gcloud compute routers nats "$NAT_ACTION" "$NAT" --router "$ROUTER" --region "$REGION" \
  --nat-external-ip-pool=gae-egress-ip --nat-custom-subnet-ip-ranges="$SUBNET" \
  --project "$PROJECT" --quiet

for ACCOUNT in gae-runtime gae-build; do
  if ! gcloud iam service-accounts describe "$ACCOUNT@$PROJECT.iam.gserviceaccount.com" \
    --project "$PROJECT" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$ACCOUNT" --project "$PROJECT" --quiet
  fi
done
RUNTIME="gae-runtime@$PROJECT.iam.gserviceaccount.com"
BUILD="gae-build@$PROJECT.iam.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member "serviceAccount:$BUILD" --role roles/run.builder --quiet >/dev/null

for NAME in "${SECRETS[@]}"; do
  gcloud secrets add-iam-policy-binding "$NAME" \
    --member "serviceAccount:$RUNTIME" --role roles/secretmanager.secretAccessor \
    --project "$PROJECT" --quiet >/dev/null
done

# Cloud Run platform request logs include URLs even when uvicorn logging is off.
# Exclude only this service's request logs from the default storage sink.
python3 - <<'PYCODE'
import json
from os import environ
import subprocess
project, service = environ['PROJECT'], environ['SERVICE']
sink = json.loads(subprocess.check_output([
    'gcloud', 'logging', 'sinks', 'describe', '_Default', '--project', project, '--format=json'
]))
name = f'{service}-requests'
log_filter = (f'resource.type="cloud_run_revision" AND resource.labels.service_name="{service}" '
              'AND log_id("run.googleapis.com/requests")')
exists = any(item['name'] == name for item in sink.get('exclusions', []))
flag = '--update-exclusion' if exists else '--add-exclusion'
subprocess.run(['gcloud', 'logging', 'sinks', 'update', '_Default', '--project', project,
                flag, f'name={name},filter={log_filter}', '--quiet'],
               check=True, stdout=subprocess.DEVNULL)
PYCODE

gcloud run deploy "$SERVICE" --source "$DEPLOY_ROOT" --project "$PROJECT" \
  --region "$REGION" --max-instances 2 --min-instances 0 --timeout 900s \
  --memory 2Gi --cpu 1 --concurrency 8 --allow-unauthenticated \
  --network "$NETWORK" --subnet "$SUBNET" --vpc-egress=all-traffic \
  --service-account "$RUNTIME" \
  --build-service-account "projects/$PROJECT/serviceAccounts/$BUILD" \
  --set-secrets 'GEMINI_API_KEY=GEMINI_API_KEY:latest,MONGODB_URI=MONGODB_URI:latest,EPC_API_TOKEN=EPC_API_TOKEN:latest,ACCESS_CODE=ACCESS_CODE:latest' \
  --set-env-vars "GEMINI_REQUESTS_PER_IP=${GEMINI_REQUESTS_PER_IP:-300},GEMINI_LIMIT_WINDOW_SECONDS=${GEMINI_LIMIT_WINDOW_SECONDS:-3600}" --quiet

EGRESS_IP="$(gcloud compute addresses describe gae-egress-ip --region "$REGION" \
  --project "$PROJECT" --format='value(address)')"
printf 'Atlas network access: add exactly %s/32 to the allowlist.\n' "$EGRESS_IP"
