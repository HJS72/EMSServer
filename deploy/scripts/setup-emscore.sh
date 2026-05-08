#!/usr/bin/env bash
# =============================================================================
# setup-emscore.sh  –  EMSCore CT einrichten (10.13.30.220)
# Services: Collector, (spaeter) Forecast, Optimizer, Dispatcher
# Ziel-OS:  Debian 12 (Bookworm)
# =============================================================================
set -euo pipefail

REPO_URL="https://github.com/HJS72/EMSServer.git"
INSTALL_DIR="/opt/ems/EMSServer"
VENV_DIR="/opt/ems/venv"
DATA_DIR="/var/lib/ems"
CONFIG_DIR="/etc/ems"
EMS_USER="ems"

echo "=== EMS Core Setup ==="

# --- System-Pakete -----------------------------------------------------------
apt-get update -qq
apt-get install -y git python3 python3-venv python3-pip sqlite3

# --- Systembenutzer ----------------------------------------------------------
if ! id "$EMS_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$EMS_USER"
    echo "  [+] Benutzer '$EMS_USER' angelegt."
fi

# --- Verzeichnisse -----------------------------------------------------------
mkdir -p "$DATA_DIR" "$CONFIG_DIR"
chown "$EMS_USER":"$EMS_USER" "$DATA_DIR"

# --- Repository --------------------------------------------------------------
if [[ -d "$INSTALL_DIR/.git" ]]; then
    echo "  [~] Repository vorhanden, aktualisiere..."
    git -C "$INSTALL_DIR" pull --ff-only
else
    git clone "$REPO_URL" "$INSTALL_DIR"
    echo "  [+] Repository geklont."
fi
chown -R "$EMS_USER":"$EMS_USER" "$(dirname "$INSTALL_DIR")"

# --- Python venv + Abhaengigkeiten -------------------------------------------
if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
    echo "  [+] venv angelegt."
fi
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q
echo "  [+] Python-Pakete installiert."

# --- Beispielkonfig kopieren wenn noch keine vorhanden -----------------------
if [[ ! -f "$CONFIG_DIR/config.yaml" ]]; then
    cp "$INSTALL_DIR/config/config.example.yaml" "$CONFIG_DIR/config.yaml"
    chmod 640 "$CONFIG_DIR/config.yaml"
    chown root:"$EMS_USER" "$CONFIG_DIR/config.yaml"
    echo ""
    echo "  [!] WICHTIG: $CONFIG_DIR/config.yaml anpassen!"
    echo "      - iobroker.host eintragen"
    echo "      - influxdb.token eintragen (oder in /etc/ems/secrets.env)"
    echo "      - Datenpunkt-IDs (id-Felder) auf echte ioBroker State-IDs setzen"
    echo ""
fi

# --- Secrets-Env Template ----------------------------------------------------
if [[ ! -f "$CONFIG_DIR/secrets.env" ]]; then
    cat > "$CONFIG_DIR/secrets.env" <<'EOF'
# EMS Secrets – nur root/ems lesbar
# EMS_INFLUX_TOKEN=dein-influxdb-api-token
EOF
    chmod 640 "$CONFIG_DIR/secrets.env"
    chown root:"$EMS_USER" "$CONFIG_DIR/secrets.env"
fi

# --- SQLite Schema initialisieren --------------------------------------------
sudo -u "$EMS_USER" "$VENV_DIR/bin/python" \
    "$INSTALL_DIR/scripts/db_init.py" --db "$DATA_DIR/ems.db"
echo "  [+] SQLite-Schema initialisiert."

# --- systemd Unit installieren -----------------------------------------------
cp "$INSTALL_DIR/deploy/systemd/ems-collector.service" \
   /etc/systemd/system/ems-collector.service
systemctl daemon-reload
systemctl enable ems-collector.service
echo "  [+] ems-collector.service aktiviert."

echo ""
echo "=== Setup abgeschlossen ==="
echo "Naechste Schritte:"
echo "  1. $CONFIG_DIR/config.yaml fertig konfigurieren"
echo "  2. InfluxDB Buckets anlegen (auf EMSDataUI):"
echo "       EMS_CONFIG=$CONFIG_DIR/config.yaml \\"
echo "         $VENV_DIR/bin/python $INSTALL_DIR/scripts/influx_setup.py"
echo "  3. Collector starten: systemctl start ems-collector"
echo "  4. Logs pruefen:      journalctl -u ems-collector -f"
