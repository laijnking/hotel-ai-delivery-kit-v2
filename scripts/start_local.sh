#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT/runtime/logs"
PYTHON="$ROOT/.venv/bin/python"

mkdir -p "$LOG_DIR"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing virtualenv Python: $PYTHON" >&2
  echo "Run: python3 -m venv .venv && .venv/bin/python -m pip install -r backend/requirements.txt" >&2
  exit 1
fi

start_backend() {
  local service="$1"
  local port="$2"

  (
    cd "$ROOT/backend/apps/$service"
    exec "$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port "$port"
  ) > "$LOG_DIR/$service.stdout.log" 2> "$LOG_DIR/$service.stderr.log" &

  echo "$!" > "$LOG_DIR/$service.pid"
}

start_backend "auth-service" 8105
start_backend "metric-service" 8102
start_backend "semantic-service" 8101
start_backend "sql-guardrail-service" 8103
start_backend "db-executor-service" 8106
start_backend "explanation-service" 8104
start_backend "audit-service" 8107
start_backend "ai-query-service" 8100

(
  cd "$ROOT/frontend"
  exec npm run dev -- --host 0.0.0.0 --port 3000
) > "$LOG_DIR/frontend.stdout.log" 2> "$LOG_DIR/frontend.stderr.log" &

echo "$!" > "$LOG_DIR/frontend.pid"

echo "HotelAgent local services started."
echo "Frontend: http://127.0.0.1:3000"
echo "Backend:  http://127.0.0.1:8100"
for ip in $(hostname -I 2>/dev/null || true); do
  echo "LAN frontend: http://$ip:3000"
  echo "LAN backend:  http://$ip:8100"
done
echo "Logs:     $LOG_DIR"

wait
