#!/usr/bin/env bash
# Start an isolated Go All-Electric instance (FastAPI backend + Vite frontend) for verification.
#
#   launch.sh [mock|real]
#
# mock (default): frontend uses Sam's built-in sample data (VITE_USE_MOCKS=true); the backend runs
#                 with no keys at all. Nothing leaves the machine.
# real:           frontend calls the live /api (VITE_USE_MOCKS=false); the backend gets only
#                 GEMINI_API_KEY and EPC_API_TOKEN from $GAE_ENV_FILE (default
#                 ~/.config/go-all-electric/.env), loaded into its own process environment.
#                 Values are never printed. MongoDB, the access-code gate and the retired
#                 ACCESS_CODE are deliberately not loaded, so surveys are not saved and the local
#                 app has no sign-in.
#
# Ports are free ports picked at launch (override with GAE_BACKEND_PORT / GAE_FRONTEND_PORT), so
# several worktrees can run side by side. State lives in <worktree>/.verify/run; source its `env`
# file to get GAE_URL, GAE_API and the chrome-devtools-axi session for this worktree.
set -euo pipefail

MODE=${1:-mock}
case "$MODE" in mock | real) ;; *) echo "usage: launch.sh [mock|real]" >&2; exit 2 ;; esac

SKILL_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
WT=$(git -C "$SKILL_DIR" rev-parse --show-toplevel)
STATE="$WT/.verify/run"
EVIDENCE="$WT/.verify/evidence"

die() { echo "launch: $*" >&2; exit 1; }
alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }
free_port() { python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'; }

if [ -f "$STATE/env" ]; then
  # shellcheck disable=SC1091
  . "$STATE/env"
  if alive "${GAE_BACKEND_PID:-}" || alive "${GAE_FRONTEND_PID:-}"; then
    die "an instance from this worktree is already running ($GAE_MODE at $GAE_URL). Run doctor.sh, or teardown.sh first."
  fi
  rm -rf "$STATE"
fi
mkdir -p "$STATE" "$EVIDENCE"

# Settings read `.env` and `../.env` relative to the backend's working directory. Run it from the
# state dir so a stray .env in the checkout can never leak keys (or a gate) into a mock run.
for stray in "$WT/.env" "$WT/backend/.env" "$WT/frontend/.env" "$WT/frontend/.env.local"; do
  [ -e "$stray" ] && echo "launch: note: $stray exists and is ignored (the launcher sets every mode variable itself)" >&2
done

[ -x "$WT/backend/.venv/bin/python" ] || (cd "$WT/backend" && uv sync --frozen >/dev/null)
[ -d "$WT/frontend/node_modules/vite" ] || (cd "$WT/frontend" && npm ci --no-audit --no-fund >/dev/null)

if [ "$MODE" = real ]; then
  ENV_FILE=${GAE_ENV_FILE:-$HOME/.config/go-all-electric/.env}
  [ -r "$ENV_FILE" ] || die "real mode needs the keys file $ENV_FILE"
  grep -Eq '^(export )?GEMINI_API_KEY=.+' "$ENV_FILE" || die "GEMINI_API_KEY is missing or empty in $ENV_FILE"
fi

BP=${GAE_BACKEND_PORT:-$(free_port)}
FP=${GAE_FRONTEND_PORT:-$(free_port)}
[ "$BP" != "$FP" ] || FP=$(free_port)
SESSION="gae-verify-$(printf %s "$WT" | shasum | cut -c1-8)"

# Exports only the allowlisted keys into the current (sub)shell. Never echo, never `set -x`.
load_keys() {
  local line name val
  while IFS= read -r line || [ -n "$line" ]; do
    line=${line#export }
    name=${line%%=*}
    case "$name" in GEMINI_API_KEY | EPC_API_TOKEN) ;; *) continue ;; esac
    val=${line#*=}
    val=${val%\"}; val=${val#\"}; val=${val%\'}; val=${val#\'}
    export "$name=$val"
  done <"$ENV_FILE"
}

SECRET_VARS="GEMINI_API_KEY EPC_API_TOKEN MONGODB_URI GOOGLE_SOLAR_API_KEY ACCESS_CODE ACCESS_CODE_HASH SESSION_SECRET"

(
  trap '' HUP
  for v in $SECRET_VARS; do unset "$v"; done
  [ "$MODE" = real ] && load_keys
  cd "$STATE"
  exec "$WT/backend/.venv/bin/python" -m uvicorn --app-dir "$WT/backend/src" gae.main:app \
    --host 127.0.0.1 --port "$BP"
) </dev/null >"$STATE/backend.log" 2>&1 &
BPID=$!

VITE_MOCKS=true
[ "$MODE" = real ] && VITE_MOCKS=false
(
  trap '' HUP
  for v in $SECRET_VARS; do unset "$v"; done
  cd "$WT/frontend"
  export GAE_API_TARGET="http://127.0.0.1:$BP" VITE_USE_MOCKS="$VITE_MOCKS"
  exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port "$FP" --strictPort --clearScreen false
) </dev/null >"$STATE/frontend.log" 2>&1 &
FPID=$!

cat >"$STATE/env" <<EOF
export GAE_MODE=$MODE
export GAE_URL=http://127.0.0.1:$FP
export GAE_API=http://127.0.0.1:$BP
export GAE_BACKEND_PID=$BPID
export GAE_FRONTEND_PID=$FPID
export GAE_WORKTREE=$WT
export GAE_REV=$(git -C "$WT" rev-parse --short HEAD)
export GAE_STARTED=$(date +%s)
export GAE_STATE=$STATE
export GAE_EVIDENCE=$EVIDENCE
export CHROME_DEVTOOLS_AXI_SESSION=$SESSION
EOF

fail() {
  echo "launch: $*" >&2
  echo "--- backend.log (tail)" >&2; tail -20 "$STATE/backend.log" >&2 || true
  echo "--- frontend.log (tail)" >&2; tail -20 "$STATE/frontend.log" >&2 || true
  "$SKILL_DIR/scripts/teardown.sh" >/dev/null 2>&1 || true
  exit 1
}

# Ready means usable: the API answers, Vite has compiled the app in the right mode, and the
# proxy reaches this run's backend (not someone else's on :8000).
for _ in $(seq 1 120); do
  alive "$BPID" || fail "backend exited during startup"
  curl -fsS "http://127.0.0.1:$BP/api/health" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fsS "http://127.0.0.1:$BP/api/health" >/dev/null 2>&1 || fail "backend not healthy after 60 s"

for _ in $(seq 1 120); do
  alive "$FPID" || fail "frontend exited during startup"
  curl -fsS "http://127.0.0.1:$FP/" 2>/dev/null | grep -q 'id="root"' && break
  sleep 0.5
done
curl -fsS "http://127.0.0.1:$FP/src/main.tsx" >/dev/null 2>&1 || fail "Vite did not compile src/main.tsx"
curl -fsS "http://127.0.0.1:$FP/src/api/client.ts" 2>/dev/null | grep -q "\"VITE_USE_MOCKS\": *\"$VITE_MOCKS\"" ||
  fail "frontend is not in $MODE mode (VITE_USE_MOCKS != $VITE_MOCKS)"
curl -fsS "http://127.0.0.1:$FP/api/health" >/dev/null 2>&1 || fail "Vite /api proxy does not reach the backend"

echo "ready: $MODE mode"
echo "  app      http://127.0.0.1:$FP   (phone harness: http://127.0.0.1:$FP/__frame.html?w=390&h=844&path=/)"
echo "  api      http://127.0.0.1:$BP/api/health  $(curl -fsS "http://127.0.0.1:$BP/api/health")"
echo "  evidence $EVIDENCE"
echo "  next     . $STATE/env && $SKILL_DIR/scripts/doctor.sh"
