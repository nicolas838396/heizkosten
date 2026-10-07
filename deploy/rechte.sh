#!/usr/bin/env bash
# Setzt die Dateirechte der Heizungsdaten: nur der Besitzer darf lesen/schreiben,
# der Funkempfang (Benutzer des Dienstes wmbusmeters) darf nur den Ordner meters.d lesen.
set -euo pipefail
BESITZER="${SUDO_USER:-$USER}"
DATEN="${HEIZKOSTEN_DATA:-/var/lib/heizkosten}"
[ -d "$DATEN" ] || exit 0
DIENST_USER="$(systemctl show wmbusmeters -p User --value 2>/dev/null || true)"
[ -n "$DIENST_USER" ] || DIENST_USER=root
sudo chown -R "$BESITZER":"$BESITZER" "$DATEN"
sudo chmod -R go-rwx "$DATEN"
if [ "$DIENST_USER" != "root" ] && id "$DIENST_USER" >/dev/null 2>&1; then
  GRUPPE="$(id -gn "$DIENST_USER")"
  sudo mkdir -p "$DATEN/meters.d"
  sudo chgrp "$GRUPPE" "$DATEN" "$DATEN/meters.d"
  sudo chmod 710 "$DATEN"              # Gruppe darf nur durchgehen
  sudo chmod 2750 "$DATEN/meters.d"    # Gruppe liest; neue Dateien erben die Gruppe
  sudo find "$DATEN/meters.d" -type f -exec chgrp "$GRUPPE" {} + -exec chmod 640 {} +
fi
echo "Rechte gesetzt (Funkempfang: $DIENST_USER)."
