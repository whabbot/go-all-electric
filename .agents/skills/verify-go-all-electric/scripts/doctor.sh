#!/usr/bin/env bash
# Read-only check: is this worktree's verification instance worth driving?
#
#   doctor.sh
#
# Exits 0 and prints "doctor: ok" only when both processes this worktree started are alive, own
# their ports, the backend reports the integrations its mode expects, the frontend is compiled in
# the same mode, its /api proxy reaches this run's backend, and the checkout has not moved since
# launch (the backend does not hot-reload).
set -uo pipefail

SKILL_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
WT=$(git -C "$SKILL_DIR" rev-parse --show-toplevel)
STATE="$WT/.verify/run"
bad=0
ok() { echo "  ok    $*"; }
no() { echo "  FAIL  $*"; bad=1; }

[ -f "$STATE/env" ] || { echo "doctor: no instance for $WT (run launch.sh)"; exit 1; }
# shellcheck disable=SC1091
. "$STATE/env"
echo "doctor: $GAE_MODE mode, app $GAE_URL, api $GAE_API, browser session $CHROME_DEVTOOLS_AXI_SESSION"

owner() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1; }
for side in backend frontend; do
  if [ "$side" = backend ]; then pid=$GAE_BACKEND_PID; port=${GAE_API##*:}; else pid=$GAE_FRONTEND_PID; port=${GAE_URL##*:}; fi
  if kill -0 "$pid" 2>/dev/null; then ok "$side pid $pid alive"; else no "$side pid $pid is not running"; continue; fi
  o=$(owner "$port")
  if [ "$o" = "$pid" ]; then ok "$side owns port $port"; else no "port $port is owned by pid ${o:-nobody}, not $pid"; fi
done

health=$(curl -fsS --max-time 5 "$GAE_API/api/health" 2>/dev/null) || health=""
if [ -z "$health" ]; then
  no "backend /api/health did not answer"
else
  ok "backend health $health"
  case "$GAE_MODE" in
    mock) echo "$health" | grep -q '"gemini":false' && echo "$health" | grep -q '"epc":false' &&
      echo "$health" | grep -q '"mongodb":false' && ok "mock backend has no keys" ||
      no "mock backend has keys configured (expected none)" ;;
    real) echo "$health" | grep -q '"gemini":true' && ok "real backend has a Gemini key" || no "real backend has no Gemini key"
      echo "$health" | grep -q '"epc":true' && ok "real backend has an EPC token" || no "real backend has no EPC token"
      echo "$health" | grep -q '"mongodb":false' && ok "MongoDB not connected (surveys are not saved)" ||
      no "real backend is connected to MongoDB (verification runs must not write surveys)" ;;
  esac
fi

want=true
[ "$GAE_MODE" = real ] && want=false
if curl -fsS --max-time 10 "$GAE_URL/src/api/client.ts" 2>/dev/null | grep -q "\"VITE_USE_MOCKS\": *\"$want\""; then
  ok "frontend compiled with VITE_USE_MOCKS=$want"
else
  no "frontend is not serving VITE_USE_MOCKS=$want"
fi
if [ "$(curl -fsS --max-time 5 "$GAE_URL/api/health" 2>/dev/null)" = "$health" ] && [ -n "$health" ]; then
  ok "frontend /api proxy reaches this backend"
else
  no "frontend /api proxy does not reach $GAE_API"
fi
curl -fsS --max-time 5 "$GAE_URL/__frame.html" 2>/dev/null | grep -q 'id="f"' && ok "phone harness /__frame.html served" ||
  no "/__frame.html missing (frontend/public/__frame.html)"

rev=$(git -C "$WT" rev-parse --short HEAD)
if [ "$rev" = "$GAE_REV" ] && git -C "$WT" diff --quiet -- backend/src; then
  ok "backend code unchanged since launch ($rev)"
else
  echo "  WARN  backend code changed since launch ($GAE_REV -> $rev or uncommitted backend/src edits): teardown.sh and launch.sh again to test it"
fi

if [ "$bad" = 0 ]; then echo "doctor: ok"; else echo "doctor: NOT OK (teardown.sh, then launch.sh)"; exit 1; fi
