#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

run_as_app() {
  local command="$1"

  if [[ "$(id -u)" -eq 0 ]]; then
    su - "$APP_USER" -s /bin/bash -c "cd '$ROOT_DIR' && $command"
  else
    bash -lc "cd '$ROOT_DIR' && $command"
  fi
}

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  . "$ROOT_DIR/.env"
  set +a
fi

BRANCH="${GITHUB_BRANCH:-main}"
APP_USER="${APP_USER:-$(stat -c '%U' "$ROOT_DIR")}" 

cd "$ROOT_DIR"

if [[ ! -d .git ]]; then
  echo "Kein Git-Repository gefunden in $ROOT_DIR"
  exit 1
fi

run_as_app "git fetch origin '$BRANCH'"
LOCAL_SHA="$(run_as_app "git rev-parse HEAD")"
REMOTE_SHA="$(run_as_app "git rev-parse 'origin/$BRANCH'")"

if [[ "$LOCAL_SHA" == "$REMOTE_SHA" ]]; then
  echo "Kein Update verfügbar"
  exit 0
fi

run_as_app "git pull --ff-only origin '$BRANCH'"
run_as_app "'$ROOT_DIR/.venv/bin/pip' install -r requirements.txt"

SERVICE_NAME="${SERVICE_NAME:-ems-server}"

if [[ "$(id -u)" -eq 0 ]]; then
  systemctl restart "$SERVICE_NAME"
else
  sudo systemctl restart "$SERVICE_NAME"
fi

echo "Update installiert: $LOCAL_SHA -> $REMOTE_SHA"
