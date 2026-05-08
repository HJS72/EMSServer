#!/usr/bin/env bash
# =============================================================================
# setup-emsdataui.sh  –  EMSDataUI CT einrichten (10.13.30.221)
# Services: InfluxDB 2.x, Grafana
# Ziel-OS:  Debian 12 (Bookworm)
# =============================================================================
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
    echo "Fehler: Skript muss als root ausgefuehrt werden (z.B. 'bash setup-emsdataui.sh' als root-User im CT)."
    exit 1
fi

INFLUX_ORG="ems"
INFLUX_USER="admin"
INFLUX_BUCKET_INIT="ems_raw"
# INFLUX_PASSWORD und INFLUX_TOKEN werden interaktiv gesetzt oder per Env uebergeben

echo "=== EMS DataUI Setup ==="

# --- System-Pakete und Voraussetzungen ---------------------------------------
apt-get update -qq
apt-get install -y curl gpg ca-certificates

# --- InfluxDB 2.x -------------------------------------------------------------
if ! command -v influxd &>/dev/null; then
    # Direkter .deb-Download umgeht sqv-Signing-Probleme auf Debian 13
    INFLUX_VERSION="2.7.11"
    ARCH=$(dpkg --print-architecture)
    INFLUX_DEB="influxdb2_${INFLUX_VERSION}_${ARCH}.deb"
    INFLUX_URL="https://dl.influxdata.com/influxdb/releases/${INFLUX_DEB}"
    echo "  Lade InfluxDB ${INFLUX_VERSION} (${ARCH})..."
    curl -fsSL "${INFLUX_URL}" -o "/tmp/${INFLUX_DEB}"
    dpkg -i "/tmp/${INFLUX_DEB}"
    rm -f "/tmp/${INFLUX_DEB}"
    echo "  [+] InfluxDB 2 installiert."
else
    echo "  [OK] InfluxDB bereits vorhanden."
fi

systemctl enable --now influxdb
echo "  [+] InfluxDB gestartet."

# --- InfluxDB initialisieren (erster Start) ----------------------------------
echo "  Warte auf InfluxDB..."
for i in $(seq 1 10); do
    influx ping &>/dev/null 2>&1 && break || sleep 3
done

if ! influx org list &>/dev/null 2>&1; then
    echo ""
    echo "  InfluxDB noch nicht eingerichtet."
    echo "  Bitte manuell aufrufen:"
    echo ""
    echo "    influx setup \\"
    echo "      --username ${INFLUX_USER} \\"
    echo "      --org ${INFLUX_ORG} \\"
    echo "      --bucket ${INFLUX_BUCKET_INIT} \\"
    echo "      --retention 720h \\"
    echo "      --force"
    echo ""
    echo "  Danach API-Token erzeugen und in /etc/ems/secrets.env auf EMSCore eintragen."
fi

# --- Grafana ------------------------------------------------------------------
if ! command -v grafana-server &>/dev/null; then
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://apt.grafana.com/gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/grafana.gpg
    chmod a+r /etc/apt/keyrings/grafana.gpg
    echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] \
https://apt.grafana.com stable main" \
        > /etc/apt/sources.list.d/grafana.list
    apt-get update -qq
    apt-get install -y grafana
    echo "  [+] Grafana installiert."
else
    echo "  [OK] Grafana bereits vorhanden."
fi

systemctl enable --now grafana-server
echo "  [+] Grafana gestartet."

# --- Firewall-Hinweise -------------------------------------------------------
echo ""
echo "=== Setup abgeschlossen ==="
echo "Zugaenge (intern):"
echo "  InfluxDB:  http://10.13.30.221:8086"
echo "  Grafana:   http://10.13.30.221:3000  (admin/admin – Passwort aendern!)"
echo ""
echo "Naechste Schritte:"
echo "  1. influx setup ausfuehren (falls noch nicht geschehen)"
echo "  2. All-Access API-Token erzeugen und in EMSCore /etc/ems/secrets.env eintragen"
echo "  3. InfluxDB Buckets anlegen (auf EMSCore nach Konfiguration):"
echo "       python scripts/influx_setup.py"
echo "  4. Grafana InfluxDB-Datasource konfigurieren (Flux Query Language)"
