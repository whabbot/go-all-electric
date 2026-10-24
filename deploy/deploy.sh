#!/usr/bin/env bash
# Run after bootstrap. Never run with shell tracing or handle secret values.
set -euo pipefail
set +x
YES=false
case "${1:-}" in
  --yes) YES=true ;;
  '') ;;
  *) printf 'Usage: %s [--yes]\n' "$0" >&2; exit 1 ;;
esac
if [[ $# -gt 1 ]]; then
  printf 'Usage: %s [--yes]\n' "$0" >&2
  exit 1
fi
ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
# build.sh owns both the dirty-tree check and the commit-tagged reference.
if ! IMAGE="$("$ROOT/deploy/build.sh" --image-reference)"; then
  printf 'Deployment stopped: could not determine an image from a clean tree.\n' >&2
  exit 1
fi
if gcloud artifacts docker images describe "$IMAGE" --quiet >/dev/null; then
  printf 'Reusing image %s\n' "$IMAGE"
else
  printf 'Image lookup failed or image is absent; building the current commit.\n' >&2
  if ! IMAGE="$("$ROOT/deploy/build.sh")"; then
    printf 'Deployment stopped: image build failed; saved image was not changed.\n' >&2
    exit 1
  fi
fi
# Validate before writing HCL; empty output must never replace a saved image.
if [[ ! "$IMAGE" =~ ^[a-z0-9.-]+-docker\.pkg\.dev/[a-z0-9.-]+/go-all-electric/go-all-electric:[0-9a-f]{40}$ ]]; then
  printf 'Deployment stopped: invalid image reference; saved image was not changed.\n' >&2
  exit 1
fi
IMAGE_FILE="$ROOT/deploy/tofu/image.auto.tfvars"
TEMP_IMAGE="$(mktemp "$IMAGE_FILE.XXXXXX")"
trap 'rm -f "$TEMP_IMAGE"' EXIT
printf 'image = "%s"\n' "$IMAGE" > "$TEMP_IMAGE"
mv -f "$TEMP_IMAGE" "$IMAGE_FILE"

PLAN_STATUS=0
tofu -chdir="$ROOT/deploy/tofu" plan -detailed-exitcode -out=deploy.plan || PLAN_STATUS=$?
case "$PLAN_STATUS" in
  0)
    printf 'No infrastructure changes.\n'
    tofu -chdir="$ROOT/deploy/tofu" output -raw service_url
    printf '\n'
    exit 0
    ;;
  2) ;;
  *) printf 'Deployment stopped: plan failed; saved image retained in image.auto.tfvars.\n' >&2; exit 1 ;;
esac
tofu -chdir="$ROOT/deploy/tofu" show deploy.plan
if [[ "$YES" != true ]]; then
  printf 'Type yes to apply this plan: '
  ANSWER=''
  if ! read -r ANSWER || [[ "$ANSWER" != yes ]]; then
    printf 'Apply cancelled; saved image retained in image.auto.tfvars.\n'
    exit 0
  fi
fi
if ! tofu -chdir="$ROOT/deploy/tofu" apply deploy.plan; then
  printf 'Deployment stopped: apply failed; saved image retained in image.auto.tfvars.\n' >&2
  exit 1
fi
tofu -chdir="$ROOT/deploy/tofu" output -raw service_url
printf '\n'
