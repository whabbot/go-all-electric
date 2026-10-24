#!/usr/bin/env bash
# Run after the bootstrap apply. Builds an image only; does not deploy it.
set -euo pipefail
set +x
PROJECT="${GOOGLE_CLOUD_PROJECT:-go-all-electric-demo}"
REGION="${GOOGLE_CLOUD_REGION:-europe-west2}"
ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
if [[ -n "$(git -C "$ROOT" status --porcelain)" ]]; then
  printf 'Commit or discard working-tree changes before building a commit-tagged image.\n' >&2
  exit 1
fi
SHA="$(git -C "$ROOT" rev-parse HEAD)"
IMAGE="$REGION-docker.pkg.dev/$PROJECT/go-all-electric/go-all-electric:$SHA"
gcloud builds submit "$ROOT" --project "$PROJECT" --region "$REGION" \
  --config "$ROOT/deploy/cloudbuild.yaml" \
  --service-account "projects/$PROJECT/serviceAccounts/gae-build@$PROJECT.iam.gserviceaccount.com" \
  --substitutions "_IMAGE=$IMAGE" --quiet >&2
printf '%s\n' "$IMAGE"
