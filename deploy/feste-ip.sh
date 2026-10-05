#!/usr/bin/env bash
# Feste IP-Adresse für den Pi setzen und WLAN-Stromsparmodus dauerhaft ausschalten.
# Aufruf:  bash deploy/feste-ip.sh 192.168.2.50
set -euo pipefail
NEU="${1:?Bitte Adresse angeben, z. B. 192.168.2.50}"
CON="$(nmcli -t -f NAME,TYPE connection show --active | grep -E ':(802-11-wireless|wifi)$' | head -1 | cut -d: -f1)"
[ -n "$CON" ] || { echo "Keine aktive WLAN-Verbindung gefunden."; exit 1; }
GW="$(ip route | awk '/default/ {print $3; exit}')"
PREFIX="$(ip -4 -o addr show wlan0 | awk '{print $4}' | cut -d/ -f2)"
echo "WLAN: $CON  Router: $GW  neue Adresse: $NEU/$PREFIX"
if ping -c1 -W1 "$NEU" >/dev/null 2>&1; then echo "ABBRUCH: $NEU wird schon von einem anderen Gerät benutzt."; exit 1; fi
sudo nmcli connection modify "$CON" 802-11-wireless.powersave 2 \
  ipv4.method manual ipv4.addresses "$NEU/$PREFIX" ipv4.gateway "$GW" ipv4.dns "$GW 1.1.1.1"
echo "Gespeichert. Aktivieren mit:  sudo systemctl restart NetworkManager"
echo "Danach ist der Pi unter http://$NEU:8080 erreichbar. Die Verbindung bricht kurz ab."
