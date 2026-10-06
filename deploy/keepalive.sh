#!/usr/bin/env bash
# Haelt den Pi im WLAN "wach": pingt alle 10 Sekunden den Router an.
# Hilft, wenn die Seite aus dem Haus-WLAN zeitweise nicht erreichbar ist.
# Aufruf:  bash deploy/keepalive.sh
set -euo pipefail
sudo tee /usr/local/bin/hk-keepalive >/dev/null <<'SCRIPT'
#!/bin/sh
while true; do
  GW="$(ip route | awk '/default/ {print $3; exit}')"
  [ -n "$GW" ] && ping -c1 -W2 "$GW" >/dev/null 2>&1
  sleep 10
done
SCRIPT
sudo chmod +x /usr/local/bin/hk-keepalive
sudo tee /etc/systemd/system/hk-keepalive.service >/dev/null <<'UNIT'
[Unit]
Description=WLAN-Keepalive fuer die Heizkosten-Webseite
After=network-online.target

[Service]
ExecStart=/usr/local/bin/hk-keepalive
Restart=always

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now hk-keepalive
echo "Keepalive laeuft: $(systemctl is-active hk-keepalive)"
