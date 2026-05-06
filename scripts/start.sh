#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  . "$ROOT_DIR/.env"
  set +a
fi

cd "$ROOT_DIR"
exec "$ROOT_DIR/.venv/bin/uvicorn" app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8080}"
