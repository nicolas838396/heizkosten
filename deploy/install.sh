#!/usr/bin/env bash
# Installiert die Heizkosten-Webseite auf dem Raspberry Pi. Kann beliebig oft wiederholt werden.
# Aufruf:  bash deploy/install.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENUTZER="${SUDO_USER:-$USER}"
DATEN=/var/lib/heizkosten
STICK="${STICK:-/dev/ttyACM0:iu891a:t1,c1}"

echo "== 1/6 Python-Umgebung"
sudo apt-get install -y python3-venv >/dev/null
[ -d "$REPO/venv" ] || python3 -m venv "$REPO/venv"
"$REPO/venv/bin/pip" install -q -r "$REPO/requirements.txt"

echo "== 2/6 Datenordner $DATEN"
sudo mkdir -p "$DATEN/meters.d"
sudo chown -R "$BENUTZER":"$BENUTZER" "$DATEN"

echo "== 3/6 wmbusmeters-Konfiguration"
command -v wmbusmeters >/dev/null || { echo "FEHLER: wmbusmeters ist nicht installiert."; exit 1; }
sudo mkdir -p /var/lib/wmbusmeters/meter_readings /var/log/wmbusmeters
if [ ! -f /etc/wmbusmeters.conf ] || ! grep -q "heizkosten" /etc/wmbusmeters.conf; then
  sudo tee /etc/wmbusmeters.conf >/dev/null <<CONF
# erzeugt von heizkosten/deploy/install.sh
device=$STICK
logtelegrams=true
format=json
meterfiles=/var/lib/wmbusmeters/meter_readings
meterfilesaction=overwrite
logfile=/var/log/wmbusmeters/wmbusmeters.log
loglevel=normal
CONF
fi
[ -e /etc/wmbusmeters.d ] && [ ! -L /etc/wmbusmeters.d ] && sudo rmdir /etc/wmbusmeters.d 2>/dev/null || true
sudo ln -sfn "$DATEN/meters.d" /etc/wmbusmeters.d

echo "== 4/6 wmbusmeters-Dienst"
if [ ! -f /etc/systemd/system/wmbusmeters.service ] && [ ! -f /lib/systemd/system/wmbusmeters.service ]; then
  sudo tee /etc/systemd/system/wmbusmeters.service >/dev/null <<UNIT
[Unit]
Description=wmbusmeters
After=network.target

[Service]
User=root
ExecStart=$(command -v wmbusmeters) --useconfig=/
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT
fi
sudo systemctl daemon-reload
sudo systemctl enable wmbusmeters >/dev/null 2>&1 || true
sudo systemctl restart wmbusmeters || echo "HINWEIS: wmbusmeters startet noch nicht (Stick steckt? Siehe: journalctl -u wmbusmeters)"
# Dateien lesbar machen, damit die Webseite sie ohne Root lesen kann
sudo chmod -R a+rX /var/lib/wmbusmeters /var/log/wmbusmeters || true

echo "== 5/6 Berechtigung zum Neustart des Empfangs"
echo "$BENUTZER ALL=(root) NOPASSWD: /usr/bin/systemctl restart wmbusmeters" | sudo tee /etc/sudoers.d/heizkosten >/dev/null
sudo chmod 440 /etc/sudoers.d/heizkosten
sudo visudo -cf /etc/sudoers.d/heizkosten >/dev/null

echo "== 6/6 Webseite als Dienst"
if [ ! -f "$DATEN/passwort.txt" ]; then
  tr -dc 'abcdefghjkmnpqrstuvwxyz23456789' </dev/urandom | head -c 10 >"$DATEN/passwort.txt" || true
  chmod 600 "$DATEN/passwort.txt"
  NEU=1
fi
sed -e "s|@USER@|$BENUTZER|g" -e "s|@REPO@|$REPO|g" -e "s|@DATA@|$DATEN|g" \
  "$REPO/deploy/heizkosten.service" | sudo tee /etc/systemd/system/heizkosten.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable heizkosten >/dev/null 2>&1
sudo systemctl restart heizkosten

IP="$(hostname -I | awk '{print $1}')"
echo
echo "Fertig. Webseite:  http://$IP:8080   (oder http://$(hostname).local:8080)"
echo "Passwort:          $(cat "$DATEN/passwort.txt")"
[ -n "${NEU:-}" ] && echo "(Benutzername beliebig, nur das Passwort zählt. Es liegt in $DATEN/passwort.txt)"
