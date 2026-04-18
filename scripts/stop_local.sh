#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT/runtime/logs"

if [[ ! -d "$LOG_DIR" ]]; then
  exit 0
fi

for pid_file in "$LOG_DIR"/*.pid; do
  [[ -e "$pid_file" ]] || continue
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
done

echo "HotelAgent local services stopped."
