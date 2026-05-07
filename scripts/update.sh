#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

ensure_safe_directory() {
  local target_user="$1"
  local config_cmd="git config --global --add safe.directory '$ROOT_DIR'"

  if [[ -z "$target_user" ]]; then
    return 0
  fi

  if [[ "$(id -u)" -eq 0 ]]; then
    su - "$target_user" -s /bin/bash -c "$config_cmd" >/dev/null 2>&1 || true
  elif [[ "$target_user" == "$(id -un)" ]]; then
    bash -lc "$config_cmd" >/dev/null 2>&1 || true
  fi
}

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

ensure_safe_directory "$APP_USER"
if [[ "$(id -u)" -eq 0 ]]; then
  git config --global --add safe.directory "$ROOT_DIR" >/dev/null 2>&1 || true
fi

if [[ ! -d .git ]]; then
  echo "Kein Git-Repository gefunden in $ROOT_DIR"
  exit 1
fi

# Ensure remote origin is set (first-time setup on server)
REPO_URL="${GITHUB_REPO_URL:-https://github.com/HJS72/EMSServer.git}"
if ! run_as_app "git remote get-url origin" &>/dev/null; then
  run_as_app "git remote add origin '$REPO_URL'"
elif [[ "$(run_as_app "git remote get-url origin")" != "$REPO_URL" ]]; then
  run_as_app "git remote set-url origin '$REPO_URL'"
fi

run_as_app "git fetch origin '$BRANCH'"
LOCAL_SHA="$(run_as_app "git rev-parse HEAD")"
REMOTE_SHA="$(run_as_app "git rev-parse 'origin/$BRANCH'")"

if [[ "$LOCAL_SHA" == "$REMOTE_SHA" ]]; then
  echo "Kein Update verfügbar"
  exit 0
fi

DATAPOINT_CONFIG_REL="data/datapoint_config.json"
DATAPOINT_CONFIG_PATH="$ROOT_DIR/$DATAPOINT_CONFIG_REL"
DATAPOINT_CONFIG_BACKUP="/tmp/ems-datapoint-config.$$.json"

if [[ -f "$DATAPOINT_CONFIG_PATH" ]]; then
  cp "$DATAPOINT_CONFIG_PATH" "$DATAPOINT_CONFIG_BACKUP" || true
fi

# Runtime files under data/ are frequently modified on productive systems and can
# block fast-forward pulls. Reset only volatile files before pulling updates.
run_as_app "git checkout -- data/latest_forecast.json data/archive '$DATAPOINT_CONFIG_REL' 2>/dev/null || true"
run_as_app "git clean -f -- data/archive 2>/dev/null || true"

# If this script was copied manually to the server, its local modification would
# block the fast-forward pull that should update it. Reset only this file before
# pulling; other local changes remain untouched and still fail loudly.
if ! run_as_app "git diff --quiet -- scripts/update.sh"; then
  echo "Setze lokale Anderung an scripts/update.sh fur Self-Update zuruck"
  run_as_app "git checkout -- scripts/update.sh"
fi

run_as_app "git pull --ff-only origin '$BRANCH'"
run_as_app "'$ROOT_DIR/.venv/bin/pip' install -r requirements.txt"

if [[ -f "$DATAPOINT_CONFIG_BACKUP" ]]; then
  cp "$DATAPOINT_CONFIG_BACKUP" "$DATAPOINT_CONFIG_PATH" || true
  if [[ -n "$APP_USER" ]]; then
    chown "$APP_USER":"$APP_USER" "$DATAPOINT_CONFIG_PATH" >/dev/null 2>&1 || true
  fi
  rm -f "$DATAPOINT_CONFIG_BACKUP"
fi

SERVICE_NAME="${SERVICE_NAME:-ems-server}"

if [[ "$(id -u)" -eq 0 ]]; then
  systemctl restart "$SERVICE_NAME"
else
  sudo systemctl restart "$SERVICE_NAME"
fi

echo "Update installiert: $LOCAL_SHA -> $REMOTE_SHA"
