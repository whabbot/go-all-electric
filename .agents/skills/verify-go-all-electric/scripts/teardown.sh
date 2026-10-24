#!/usr/bin/env bash
# Stop only what this worktree's launch.sh started, then remove the run state. Evidence stays.
#
#   teardown.sh
#
# Kills the two recorded PIDs (never by process name), stops this worktree's chrome-devtools-axi
# session, and deletes <worktree>/.verify/run. <worktree>/.verify/evidence is never touched.
set -uo pipefail

SKILL_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
WT=$(git -C "$SKILL_DIR" rev-parse --show-toplevel)
STATE="$WT/.verify/run"

[ -f "$STATE/env" ] || { echo "teardown: nothing running for $WT"; exit 0; }
# shellcheck disable=SC1091
. "$STATE/env"

stop_pid() {
  local pid=$1 name=$2
  kill -0 "$pid" 2>/dev/null || { echo "teardown: $name ($pid) already stopped"; return; }
  kill -TERM "$pid" 2>/dev/null
  for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
  kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null
  echo "teardown: stopped $name ($pid)"
}
stop_pid "$GAE_FRONTEND_PID" frontend
stop_pid "$GAE_BACKEND_PID" backend
chrome-devtools-axi stop >/dev/null 2>&1 && echo "teardown: stopped browser session $CHROME_DEVTOOLS_AXI_SESSION"

for port in "${GAE_URL##*:}" "${GAE_API##*:}"; do
  o=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1)
  [ -z "$o" ] || echo "teardown: WARN port $port is still held by pid $o (not ours; left alone)"
done
rm -rf "$STATE"
echo "teardown: done; evidence kept in $GAE_EVIDENCE"
