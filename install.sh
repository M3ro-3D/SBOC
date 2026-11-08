#!/usr/bin/env bash
set -Eeuo pipefail
if [[ $EUID -ne 0 ]]; then echo 'Bitte mit sudo ausführen.'; exit 1; fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$ROOT/sboc/agent.py" ]] || { echo 'Paket unvollständig'; exit 1; }
printf '\nSBOC. 0.2.34 Stable\n'
CONTROLLER_INSTALLED=0
AGENT_INSTALLED=0
if [[ -f /etc/systemd/system/sboc-controller.service ]]; then CONTROLLER_INSTALLED=1; fi
if [[ -f /etc/systemd/system/sboc-agent.service ]]; then AGENT_INSTALLED=1; fi
if (( CONTROLLER_INSTALLED )); then
 ROLE=controller
 echo 'Vorhandene Installation erkannt: Controller (mit Agent).'
elif (( AGENT_INSTALLED )); then
 ROLE=agent
 echo 'Vorhandene Installation erkannt: Agent.'
else
 printf '1) Controller (Weboberfläche + Überwachung + LEDs)\n2) Agent (Linux SBC)\n'
 read -rp 'Auswahl [1/2]: ' ROLE
 case "$ROLE" in 1) ROLE=controller;;2) ROLE=agent;;*) echo 'Ungültige Auswahl'; exit 1;; esac
fi
START_SECONDS=$SECONDS
STEP=0
step() { STEP=$((STEP+1)); printf '\n[%s/7] %s ...\n' "$STEP" "$1"; }
finished() { printf '      OK (%ss seit Start)\n' "$((SECONDS-START_SECONDS))"; }
trap 'echo "FEHLER: Installation bei Zeile $LINENO abgebrochen (Exit-Code $?)." >&2' ERR
step 'Hardware und Systemvoraussetzungen prüfen'
LED_MODE=simulation
if [[ "$ROLE" == controller ]]; then
 MODEL="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
 if [[ "$MODEL" == *'Raspberry Pi 3 Model B'* ]]; then LED_MODE=hardware; fi
fi
command -v python3 >/dev/null || { echo 'Python 3 fehlt'; exit 1; }
finished
step "Benötigte Pakete prüfen"
NEEDED=()
if command -v dpkg-query >/dev/null && command -v apt-get >/dev/null; then
 PACKAGES=(avahi-daemon avahi-utils python3-cryptography)
 if [[ "$ROLE" == controller ]]; then PACKAGES+=(python3-venv python3-dev build-essential); fi
 for pkg in "${PACKAGES[@]}"; do
  if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -qx 'install ok installed'; then NEEDED+=("$pkg"); fi
 done
 if (( ${#NEEDED[@]} )); then echo "Fehlende Pakete: ${NEEDED[*]}"; apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y "${NEEDED[@]}"; else echo "Alle Systempakete bereits vorhanden."; fi
fi
finished
step "Installationsverzeichnisse vorbereiten und Daten migrieren"
install -d -m 755 /opt/sboc
install -d -m 700 /var/lib/sboc
install -d -m 700 /var/lib/sboc-agent
# Prefer the latest installed SPOC state, falling back to the older SBC Monitor state.
# Never overwrite an existing SBOC configuration. Preserve the source for rollback.
if [[ "$ROLE" == controller && ! -f /var/lib/sboc/config.json ]]; then
 for OLD_DATA in /var/lib/spoc /var/lib/sbc-monitor; do
  if [[ -f "$OLD_DATA/config.json" ]]; then
   cp -a "$OLD_DATA/." /var/lib/sboc/
   echo "Bestehende Einstellungen und Daten aus $OLD_DATA übernommen."
   break
  fi
 done
fi
chmod 700 /var/lib/sboc
if [[ "$ROLE" == controller ]]; then
 if ! id sboc-web >/dev/null 2>&1; then useradd --system --no-create-home --shell /usr/sbin/nologin sboc-web; fi
 # Migration: keep all controller state, secrets, SQLite and agent trust data.
 chown -R sboc-web:sboc-web /var/lib/sboc
 chmod 700 /var/lib/sboc
fi
# Atomic application code replacement, no modification of old installation.
finished
step "Programmdateien installieren"
STAGE="$(mktemp -d /opt/sboc/.release.XXXXXXXX)"
trap 'rm -rf "$STAGE"' EXIT
cp -a "$ROOT/sboc" "$STAGE/"
rm -rf "$STAGE/sboc/__pycache__"
if [[ -d /opt/sboc/sboc ]]; then
 rm -rf /opt/sboc/sboc.previous
 mv /opt/sboc/sboc /opt/sboc/sboc.previous
fi
mv "$STAGE/sboc" /opt/sboc/sboc
# Sora is the original CURNT login font. Download missing static cuts only.
FONT_DIR=/opt/sboc/sboc/assets/fonts
mkdir -p "$FONT_DIR"
FONT_BASE=https://raw.githubusercontent.com/sora-xor/sora-font/master/fonts/ttf/v2.1beta
FONT_MISSING=0
for FONT in Sora-Regular.ttf Sora-SemiBold.ttf Sora-Bold.ttf Sora-ExtraBold.ttf; do
 if [[ ! -s "$FONT_DIR/$FONT" ]]; then
  # Preserve fonts from an earlier installation when present.
  if [[ -s "/opt/sboc/sboc.previous/assets/fonts/$FONT" ]]; then
   cp "/opt/sboc/sboc.previous/assets/fonts/$FONT" "$FONT_DIR/$FONT"
  elif [[ -s "/opt/curnt/assets/fonts/$FONT" ]]; then
   cp "/opt/curnt/assets/fonts/$FONT" "$FONT_DIR/$FONT"
  elif command -v curl >/dev/null 2>&1; then
   echo "Sora-Schrift laden: $FONT"
   if ! curl -fsSL --connect-timeout 5 --max-time 20 "$FONT_BASE/$FONT" -o "$FONT_DIR/$FONT.tmp"; then
    rm -f "$FONT_DIR/$FONT.tmp"
    FONT_MISSING=1
   else
    mv "$FONT_DIR/$FONT.tmp" "$FONT_DIR/$FONT"
   fi
  else
   FONT_MISSING=1
  fi
 fi
done
if (( FONT_MISSING )); then echo "Hinweis: Sora nicht vollständig verfügbar; Browser verwendet Ersatzschrift."; fi
finished
step "Python-Umgebung und LED-Treiber prüfen"
if [[ "$ROLE" == controller ]]; then
 if [[ ! -x /opt/sboc/venv/bin/python ]]; then python3 -m venv /opt/sboc/venv; fi
 if [[ "$LED_MODE" == hardware ]] && ! /opt/sboc/venv/bin/python -c 'import rpi_ws281x' >/dev/null 2>&1; then
  /opt/sboc/venv/bin/pip install 'rpi_ws281x>=5,<6'
 fi
 EXEC=/opt/sboc/venv/bin/python
else EXEC="$(command -v python3)"; fi
finished
step "Systemdienste einrichten"
if [[ "$ROLE" == controller ]]; then
 /opt/sboc/venv/bin/python -c 'import cryptography' >/dev/null 2>&1 || /opt/sboc/venv/bin/pip install 'cryptography>=41,<47'
fi
cat >/usr/local/bin/sboc-pairing-code <<'WRAPPER'
#!/bin/sh
cd /opt/sboc || exit 1
if [ -x /opt/sboc/venv/bin/python ]; then PY=/opt/sboc/venv/bin/python; else PY=/usr/bin/python3; fi
exec runuser -u sboc-agent -- "$PY" -m sboc.agent --pairing-code
WRAPPER
chmod 755 /usr/local/bin/sboc-pairing-code
cat >/usr/local/bin/sboc-setup-code <<'WRAPPER'
#!/bin/sh
if [ "$(id -u)" -ne 0 ]; then echo "Bitte sudo verwenden." >&2; exit 1; fi
if [ ! -f /var/lib/sboc/setup-code ]; then echo "Kein Einrichtungscode vorhanden (Einrichtung bereits abgeschlossen?)."; exit 1; fi
cat /var/lib/sboc/setup-code
WRAPPER
chmod 755 /usr/local/bin/sboc-setup-code

if ! id sboc-agent >/dev/null 2>&1; then useradd --system --no-create-home --shell /usr/sbin/nologin sboc-agent; fi
chown sboc-agent:sboc-agent /var/lib/sboc-agent
chmod 700 /var/lib/sboc-agent
AGENT_GROUP_LINE=""
if getent group systemd-journal >/dev/null 2>&1; then AGENT_GROUP_LINE='SupplementaryGroups=systemd-journal'; fi
cat >/etc/systemd/system/sboc-agent.service <<UNIT
[Unit]
Description=SBOC. lightweight Linux agent
After=network.target
[Service]
Type=simple
ExecStart=$EXEC -m sboc.agent --port 8765
WorkingDirectory=/opt/sboc
Environment=PYTHONPATH=/opt/sboc
Restart=always
RestartSec=3
User=sboc-agent
$AGENT_GROUP_LINE
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/sboc-agent
[Install]
WantedBy=multi-user.target
UNIT
if command -v avahi-publish-service >/dev/null; then
 cat >/etc/systemd/system/sboc-discovery.service <<'UNIT'
[Unit]
Description=Advertise SBOC. agent via mDNS
After=network-online.target avahi-daemon.service sboc-agent.service
Wants=network-online.target
[Service]
ExecStart=/usr/bin/avahi-publish-service -s SBOC _sboc._tcp 8765
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
fi
if [[ "$ROLE" == controller ]]; then
 CONTROLLER_FLAGS=""
 if [[ "$LED_MODE" != hardware ]]; then
  CONTROLLER_FLAGS='--simulate'
  systemctl disable --now sboc-led.service 2>/dev/null || true
 else
  cat >/etc/systemd/system/sboc-led.service <<UNIT
[Unit]
Description=SBOC. privileged LED hardware driver
After=local-fs.target
[Service]
Type=simple
ExecStart=$EXEC -m sboc.led_service
WorkingDirectory=/opt/sboc
Environment=PYTHONPATH=/opt/sboc
RuntimeDirectory=sboc-led
RuntimeDirectoryMode=0750
Group=sboc-web
User=root
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
 fi
 cat >/etc/systemd/system/sboc-controller.service <<UNIT
[Unit]
Description=SBOC. LED controller and web UI
After=network.target sboc-led.service
[Service]
Type=simple
ExecStart=$EXEC -m sboc.controller --config /var/lib/sboc/config.json --port 8088 $CONTROLLER_FLAGS
WorkingDirectory=/opt/sboc
Environment=PYTHONPATH=/opt/sboc
Restart=always
RestartSec=3
User=sboc-web
Group=sboc-web
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/sboc
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
fi
# Stop old services before new ones bind to the same ports.
for service in spoc-controller spoc-discovery spoc-agent sbc-monitor-controller sbc-monitor-discovery sbc-monitor-agent; do
 if systemctl list-unit-files "$service.service" --no-legend 2>/dev/null | grep -q "$service.service"; then
  systemctl disable --now "$service.service" || true
 fi
done
finished
step "Dienste starten und Funktion prüfen"
systemctl daemon-reload
systemctl enable --now sboc-agent.service
systemctl restart sboc-agent.service
if [[ -f /etc/systemd/system/sboc-discovery.service ]]; then
 systemctl enable --now avahi-daemon.service sboc-discovery.service || echo 'mDNS nicht gestartet; IP-Einrichtung bleibt möglich.'
fi
if [[ "$ROLE" == controller ]]; then
 if [[ "$LED_MODE" == hardware ]]; then
  systemctl enable --now sboc-led.service
  systemctl restart sboc-led.service
 fi
 systemctl enable --now sboc-controller.service
 systemctl restart sboc-controller.service
fi
sleep 1
systemctl is-active --quiet sboc-agent.service || { echo 'Agent konnte nicht starten'; exit 1; }
if [[ "$ROLE" == controller ]]; then
 if [[ "$LED_MODE" == hardware ]]; then
  systemctl is-active --quiet sboc-led.service || { echo 'LED-Dienst konnte nicht starten'; exit 1; }
 fi
 systemctl is-active --quiet sboc-controller.service || { echo 'Controller konnte nicht starten'; exit 1; }
 IP_ADDR="$(hostname -I 2>/dev/null | awk '{print $1}')"
 echo "Weboberfläche: http://${IP_ADDR:-<IP-DES-CONTROLLERS>}:8088"
fi
finished
printf '\nSBOC. Installation abgeschlossen (%s). Dauer: %ss.\n' "$ROLE" "$((SECONDS-START_SECONDS))"
