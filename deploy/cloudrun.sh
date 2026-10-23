#!/usr/bin/env bash
# Run only after gcloud auth login and selection of a billed Google Cloud project.
set -euo pipefail
set +x
: "${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT to the billed project ID}"
PROJECT="$GOOGLE_CLOUD_PROJECT"
SERVICE="${CLOUD_RUN_SERVICE:-go-all-electric}"
REGION=europe-west2
DEPLOY_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
SECRETS_FILE="${HOME}/.config/go-all-electric/.env"
export PROJECT SECRETS_FILE SERVICE

# Validate all required values before making changes; never source shell code or print values.
python3 - <<'PYCODE'
import os
import shlex
from pathlib import Path
values = {}
for line in Path(os.environ['SECRETS_FILE']).read_text().splitlines():
    line = line.strip()
    if not line or line.startswith('#'):
        continue
    if line.startswith('export '):
        line = line[7:]
    key, sep, raw = line.partition('=')
    if sep:
        parts = shlex.split(raw, comments=True)
        values[key.strip()] = ' '.join(parts)
required = ('GEMINI_API_KEY', 'MONGODB_URI', 'EPC_API_TOKEN', 'ACCESS_CODE')
missing = [key for key in required if not values.get(key)]
if missing:
    raise SystemExit('Missing nonempty values in deployment env file: ' + ', '.join(missing))
PYCODE

gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com iam.googleapis.com logging.googleapis.com \
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

python3 - <<'PYCODE'
import os
import shlex
import subprocess
from pathlib import Path
values = {}
for line in Path(os.environ['SECRETS_FILE']).read_text().splitlines():
    line = line.strip()
    if not line or line.startswith('#'):
        continue
    if line.startswith('export '):
        line = line[7:]
    key, sep, raw = line.partition('=')
    if sep:
        values[key.strip()] = ' '.join(shlex.split(raw, comments=True))
project = os.environ['PROJECT']
for name in ('GEMINI_API_KEY', 'MONGODB_URI', 'EPC_API_TOKEN', 'ACCESS_CODE'):
    common = ['--project', project, '--quiet']
    exists = subprocess.run(['gcloud', 'secrets', 'describe', name, *common],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not exists:
        subprocess.run(['gcloud', 'secrets', 'create', name, '--replication-policy=automatic',
                        *common], check=True, stdout=subprocess.DEVNULL)
    # Values travel on stdin, never argv, build context, or generated files.
    subprocess.run(['gcloud', 'secrets', 'versions', 'add', name, '--data-file=-', *common],
                   input=values[name].encode(), check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['gcloud', 'secrets', 'add-iam-policy-binding', name,
                    '--member', f'serviceAccount:gae-runtime@{project}.iam.gserviceaccount.com',
                    '--role', 'roles/secretmanager.secretAccessor', *common],
                   check=True, stdout=subprocess.DEVNULL)
PYCODE

# Cloud Run platform request logs include URLs even when uvicorn logging is off.
# Exclude only this service's request logs from the default storage sink.
python3 - <<'PYCODE'
import json
import os
import subprocess
project, service = os.environ['PROJECT'], os.environ['SERVICE']
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
  --service-account "$RUNTIME" \
  --build-service-account "projects/$PROJECT/serviceAccounts/$BUILD" \
  --set-secrets 'GEMINI_API_KEY=GEMINI_API_KEY:latest,MONGODB_URI=MONGODB_URI:latest,EPC_API_TOKEN=EPC_API_TOKEN:latest,ACCESS_CODE=ACCESS_CODE:latest' \
  --set-env-vars "GEMINI_REQUESTS_PER_IP=${GEMINI_REQUESTS_PER_IP:-300},GEMINI_LIMIT_WINDOW_SECONDS=${GEMINI_LIMIT_WINDOW_SECONDS:-3600}" --quiet
