#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Bitte mit sudo ausführen.'; exit 1; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$ROOT/sboc/agent.py" && -f "$ROOT/sboc/controller.py" ]] || { echo 'Paket unvollständig'; exit 1; }
echo 'SBOC. 0.2.43'
START_SECONDS=$SECONDS
STEP=0
step() { STEP=$((STEP+1)); printf '\n[%s/7] %s ...\n' "$STEP" "$1"; }
finished() { printf '      OK (%ss seit Start)\n' "$((SECONDS-START_SECONDS))"; }
stage=''
swapped=0
committed=0
rollback() {
  code=$?
  trap - EXIT
  if [[ $code -ne 0 && $swapped -eq 1 && $committed -eq 0 ]]; then
    echo '      Installation fehlgeschlagen: vorherigen Programmstand wiederherstellen.' >&2
    rm -rf /opt/sboc/sboc
    if [[ -d /opt/sboc/sboc.previous ]]; then mv /opt/sboc/sboc.previous /opt/sboc/sboc; fi
    if [[ -n $stage && -d $stage/units ]]; then
      for name in sboc-agent sboc-controller sboc-led sboc-discovery; do
        if [[ -f $stage/units/$name.service ]]; then
          cp -a "$stage/units/$name.service" "/etc/systemd/system/$name.service"
        else
          systemctl disable --now "$name.service" 2>/dev/null || true
          rm -f "/etc/systemd/system/$name.service"
        fi
      done
      systemctl daemon-reload || true
      systemctl try-restart sboc-agent.service sboc-controller.service sboc-led.service 2>/dev/null || true
    fi
  fi
  if [[ -n $stage && -d $stage ]]; then rm -rf "$stage"; fi
  if [[ $code -ne 0 ]]; then echo "FEHLER: Installation abgebrochen (Exit-Code $code)." >&2; fi
  exit "$code"
}
trap rollback EXIT
if [[ -f /etc/systemd/system/sboc-controller.service ]]; then ROLE=controller
elif [[ -f /etc/systemd/system/sboc-agent.service ]]; then ROLE=agent
else
 printf '1) Controller (Weboberfläche + Überwachung + LEDs)\n2) Agent (Linux SBC)\n'
 read -rp 'Auswahl [1/2]: ' choice
 case "$choice" in 1) ROLE=controller;;2) ROLE=agent;;*) echo 'Ungültige Auswahl';exit 1;;esac
fi
echo "Installationsmodus: $ROLE"
step 'Hardware und Systemvoraussetzungen prüfen'
command -v python3 >/dev/null || { echo 'Python 3 fehlt';exit 1; }
finished
step 'Systempakete und Download-Werkzeuge prüfen'
if command -v dpkg-query >/dev/null && command -v apt-get >/dev/null; then
 packages=(avahi-daemon avahi-utils python3-cryptography ca-certificates)
 if [[ "$ROLE" == controller ]];then packages+=(curl python3-venv python3-dev build-essential);fi
 missing=()
 for pkg in "${packages[@]}";do dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -qx 'install ok installed' || missing+=("$pkg");done
 if ((${#missing[@]}));then apt-get update;DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing[@]}";fi
fi
if [[ "$ROLE" == controller ]]; then command -v curl >/dev/null || { echo 'curl fehlt. Font-Download nicht möglich.' >&2; exit 1; }; fi
finished
step 'Installationsverzeichnisse und vorhandene Daten vorbereiten'
install -d -m 755 /opt/sboc
install -d -m 700 /var/lib/sboc /var/lib/sboc-agent
if [[ "$ROLE" == controller && ! -f /var/lib/sboc/config.json ]];then
 for old in /var/lib/spoc /var/lib/sbc-monitor;do
  if [[ -f "$old/config.json" ]];then cp -a "$old/." /var/lib/sboc/;break;fi
 done
fi
if ! id sboc-agent >/dev/null 2>&1;then useradd --system --no-create-home --shell /usr/sbin/nologin sboc-agent;fi
chown sboc-agent:sboc-agent /var/lib/sboc-agent
if [[ "$ROLE" == controller ]];then
 if ! id sboc-web >/dev/null 2>&1;then useradd --system --no-create-home --shell /usr/sbin/nologin sboc-web;fi
 chown -R sboc-web:sboc-web /var/lib/sboc
fi
finished
step 'Programmdateien und Schriftarten bereitstellen'
# Keep the installed environment and all persistent state; replace only program files.
stage="$(mktemp -d /opt/sboc/.release.XXXXXXXX)"
cp -a "$ROOT/sboc" "$stage/"
find "$stage/sboc" -type d -name __pycache__ -prune -exec rm -rf {} +
# Acquire fonts BEFORE replacing the working program files.
if [[ "$ROLE" == controller ]]; then
# Reuse verified local files if available, otherwise fetch the original Sora cuts.
FONT_DIR="$stage/sboc/assets/fonts"
install -d -m 755 "$FONT_DIR"
FONT_BASE='https://raw.githubusercontent.com/sora-xor/sora-font/master/fonts/ttf/v2.1beta'
for font in Sora-Regular.ttf Sora-SemiBold.ttf Sora-Bold.ttf Sora-ExtraBold.ttf; do
  if [[ -s "/opt/sboc/sboc/assets/fonts/$font" ]]; then
    cp "/opt/sboc/sboc/assets/fonts/$font" "$FONT_DIR/$font"
  elif [[ -s "/opt/curnt/assets/fonts/$font" ]]; then
    cp "/opt/curnt/assets/fonts/$font" "$FONT_DIR/$font"
  else
    echo "      Lade Sora-Schrift: $font"
    curl --fail --location --silent --show-error --retry 2 --connect-timeout 10 --max-time 60 \
      "$FONT_BASE/$font" -o "$FONT_DIR/$font.tmp" || {
        echo "Font-Download fehlgeschlagen: $font. Bisherige Installation bleibt erhalten." >&2
        exit 1
      }
    [[ -s "$FONT_DIR/$font.tmp" ]] || { echo "Leere Font-Datei: $font" >&2; exit 1; }
    mv "$FONT_DIR/$font.tmp" "$FONT_DIR/$font"
  fi
done
# Minimal signature check for OpenType/TrueType font files.
for font in "$FONT_DIR"/*.ttf; do
  magic="$(od -An -tx1 -N4 "$font" | tr -d ' \n')"
  [[ "$magic" == 00010000 || "$magic" == 4f54544f || "$magic" == 74727565 ]] || {
    echo "Ungültige Schriftdatei: $font" >&2; exit 1;
  }
done
fi
finished
step 'Python-Umgebung und LED-Treiber prüfen'
if [[ "$ROLE" == controller ]];then
 if [[ ! -x /opt/sboc/venv/bin/python ]];then python3 -m venv /opt/sboc/venv;fi
 PY=/opt/sboc/venv/bin/python
 "$PY" -c 'import cryptography' >/dev/null 2>&1 || /opt/sboc/venv/bin/pip install 'cryptography>=41,<47'
else PY="$(command -v python3)";fi
# Verify imports and install optional hardware driver before touching the running program.
"$PY" -c 'import cryptography; from cryptography.hazmat.primitives.ciphers.aead import AESGCM'
if [[ "$ROLE" == controller ]]; then
  MODEL="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
  LED_MODE=simulation
  if [[ "$MODEL" == *'Raspberry Pi 3 Model B'* ]]; then LED_MODE=hardware; fi
  if [[ "$LED_MODE" == hardware ]]; then
    "$PY" -c 'import rpi_ws281x' >/dev/null 2>&1 || /opt/sboc/venv/bin/pip install 'rpi_ws281x>=5,<6'
    "$PY" -c 'import rpi_ws281x'
  fi
fi
# Verify staged Python sources before replacing the installed code.
"$PY" -m compileall -q "$stage/sboc"
finished
step 'Systemdienste und Hilfsprogramme einrichten'
install -d -m 700 "$stage/units"
for name in sboc-agent sboc-controller sboc-led sboc-discovery; do
  if [[ -f /etc/systemd/system/$name.service ]]; then
    cp -a "/etc/systemd/system/$name.service" "$stage/units/$name.service"
  fi
done
if [[ -d /opt/sboc/sboc ]]; then
  rm -rf /opt/sboc/sboc.previous
  mv /opt/sboc/sboc /opt/sboc/sboc.previous
fi
swapped=1
mv "$stage/sboc" /opt/sboc/sboc
cat >/usr/local/bin/sboc-pairing-code <<'WRAPPER'
#!/bin/sh
cd /opt/sboc || exit 1
if [ -x /opt/sboc/venv/bin/python ];then PY=/opt/sboc/venv/bin/python;else PY=/usr/bin/python3;fi
exec runuser -u sboc-agent -- "$PY" -m sboc.agent --pairing-code
WRAPPER
chmod 755 /usr/local/bin/sboc-pairing-code
cat >/usr/local/bin/sboc-setup-code <<'WRAPPER'
#!/bin/sh
if [ "$(id -u)" -ne 0 ];then echo 'Bitte sudo verwenden.' >&2;exit 1;fi
if [ ! -f /var/lib/sboc/setup-code ];then echo 'Kein Einrichtungscode vorhanden.';exit 1;fi
cat /var/lib/sboc/setup-code
WRAPPER
chmod 755 /usr/local/bin/sboc-setup-code
journal_group=''
if getent group systemd-journal >/dev/null;then journal_group='SupplementaryGroups=systemd-journal';fi
cat >/etc/systemd/system/sboc-agent.service <<UNIT
[Unit]
Description=SBOC. lightweight Linux agent
After=network.target
[Service]
Type=simple
ExecStart=$PY -m sboc.agent --port 8765
WorkingDirectory=/opt/sboc
Environment=PYTHONPATH=/opt/sboc
Restart=always
RestartSec=3
User=sboc-agent
$journal_group
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/sboc-agent
[Install]
WantedBy=multi-user.target
UNIT
if command -v avahi-publish-service >/dev/null;then
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
if [[ "$ROLE" == controller ]];then
 MODEL="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
 LED_MODE=simulation
 if [[ "$MODEL" == *'Raspberry Pi 3 Model B'* ]];then LED_MODE=hardware;fi
 if [[ "$LED_MODE" == hardware ]];then
  cat >/etc/systemd/system/sboc-led.service <<UNIT
[Unit]
Description=SBOC. privileged LED hardware driver
After=local-fs.target
[Service]
Type=simple
ExecStart=$PY -m sboc.led_service
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
  FLAGS=''
 else
  FLAGS='--simulate'
 fi
 cat >/etc/systemd/system/sboc-controller.service <<UNIT
[Unit]
Description=SBOC. LED controller and web UI
After=network.target sboc-led.service
[Service]
Type=simple
ExecStart=$PY -m sboc.controller --config /var/lib/sboc/config.json --port 8088 $FLAGS
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
for old in spoc-controller spoc-discovery spoc-agent sbc-monitor-controller sbc-monitor-discovery sbc-monitor-agent;do
 if systemctl list-unit-files "$old.service" --no-legend 2>/dev/null | grep -q "$old.service";then systemctl disable --now "$old.service" || true;fi
done
systemctl daemon-reload
systemctl enable sboc-agent.service
systemctl restart sboc-agent.service
if [[ -f /etc/systemd/system/sboc-discovery.service ]];then
 systemctl enable --now avahi-daemon.service sboc-discovery.service || echo 'mDNS nicht gestartet; IP-Einrichtung bleibt möglich.'
fi
if [[ "$ROLE" == controller ]];then
 if [[ "$LED_MODE" == hardware ]];then
  systemctl enable sboc-led.service
  systemctl restart sboc-led.service
 else systemctl disable --now sboc-led.service 2>/dev/null || true;fi
 systemctl enable sboc-controller.service
 systemctl restart sboc-controller.service
fi
finished
step 'Dienststatus und Installation prüfen'
sleep 1
systemctl is-active --quiet sboc-agent.service || { echo 'Agent konnte nicht starten';exit 1; }
if [[ "$ROLE" == controller ]];then
 systemctl is-active --quiet sboc-controller.service || { echo 'Controller konnte nicht starten';exit 1; }
 if [[ "$LED_MODE" == hardware ]];then systemctl is-active --quiet sboc-led.service || { echo 'LED-Dienst konnte nicht starten';exit 1; };fi
 ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
 echo "Weboberfläche: http://${ip:-<IP-DES-CONTROLLERS>}:8088"
fi
finished
committed=1
printf '\nSBOC. 0.2.43 installiert. Dauer: %ss.\n' "$((SECONDS-START_SECONDS))"
