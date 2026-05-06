#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_FILE="/etc/systemd/system/ems-server.service"
UPDATER_SERVICE_FILE="/etc/systemd/system/ems-updater.service"
UPDATER_TIMER_FILE="/etc/systemd/system/ems-updater.timer"

if [[ "$(id -u)" -eq 0 ]]; then
	SUDO=()
else
	SUDO=(sudo)
fi

"${SUDO[@]}" cp "$ROOT_DIR/deploy/systemd/ems-server.service" "$SERVICE_FILE"
"${SUDO[@]}" cp "$ROOT_DIR/deploy/systemd/ems-updater.service" "$UPDATER_SERVICE_FILE"
"${SUDO[@]}" cp "$ROOT_DIR/deploy/systemd/ems-updater.timer" "$UPDATER_TIMER_FILE"

"${SUDO[@]}" sed -i "s|__WORKDIR__|$ROOT_DIR|g" "$SERVICE_FILE" "$UPDATER_SERVICE_FILE"
"${SUDO[@]}" sed -i "s|__USER__|$USER|g" "$SERVICE_FILE"
"${SUDO[@]}" sed -i "s|__APP_USER__|$USER|g" "$UPDATER_SERVICE_FILE"

"${SUDO[@]}" systemctl daemon-reload
"${SUDO[@]}" systemctl enable --now ems-server.service
"${SUDO[@]}" systemctl enable --now ems-updater.timer

echo "systemd Services aktiviert"
