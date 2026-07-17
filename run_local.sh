#!/usr/bin/env bash
# Launch all five FastAPI services locally (RUN_OFFLINE mode, sqlite + StubLLM).
# Usage: ./run_local.sh   (requires a venv with deps installed)
set -e
export RUN_OFFLINE=true
export DATABASE_URL="sqlite+aiosqlite:///./aipr.db"
export GITHUB_WEBHOOK_SECRET="dev-secret"
export PYTHONPATH="$(cd "$(dirname "$0")" && pwd)"

pids=()
start() {
  local name="$1" port="$2"
  uvicorn "${name}.main:app" --host 0.0.0.0 --port "$port" --log-level info &
  pids+=($!)
  echo "started ${name} on :${port} (pid $!)"
}

start gateway 8000
start webhook 8001
start orchestrator 8002
start reviewer 8003
start learner 8004

trap 'kill ${pids[*]} 2>/dev/null' EXIT
echo "All services up. Ctrl+C to stop."
wait
