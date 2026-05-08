#!/usr/bin/env bash
# =============================================================================
# setup-emsdataui.sh  –  EMSDataUI CT einrichten (10.13.30.221)
# Services: InfluxDB 2.x, Grafana
# Ziel-OS:  Debian 12 (Bookworm)
# =============================================================================
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

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
    mkdir -p /etc/apt/keyrings
    GNUPGHOME=$(mktemp -d)
    chmod 700 "${GNUPGHOME}"
    gpg --batch --homedir "${GNUPGHOME}" --keyserver hkps://keyserver.ubuntu.com \
        --recv-keys DA61C26A0585BD3B
    gpg --batch --homedir "${GNUPGHOME}" --export DA61C26A0585BD3B > /tmp/influx-key.asc
    gpg --batch --yes --dearmor -o /etc/apt/keyrings/influxdata.gpg /tmp/influx-key.asc
    rm -rf "${GNUPGHOME}" /tmp/influx-key.asc
    chmod a+r /etc/apt/keyrings/influxdata.gpg
    echo "deb [signed-by=/etc/apt/keyrings/influxdata.gpg] https://repos.influxdata.com/debian stable main" \
        > /etc/apt/sources.list.d/influxdata.list
    apt-get update -qq
    apt-get install -y -o Dpkg::Options::="--force-confold" influxdb2
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
    apt-get install -y -o Dpkg::Options::="--force-confold" grafana
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
