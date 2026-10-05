#!/usr/bin/env bash
# Benutzername und Passwort der Webseite festlegen. Aufruf:  bash deploy/zugang.sh
set -euo pipefail
DATEN=/var/lib/heizkosten
read -r -p "Neuer Benutzername: " BENUTZER
read -r -s -p "Neues Passwort (mind. 8 Zeichen): " PW; echo
read -r -s -p "Passwort wiederholen: " PW2; echo
[ -n "$BENUTZER" ] || { echo "Benutzername fehlt."; exit 1; }
[ "$PW" = "$PW2" ] || { echo "Passwörter stimmen nicht überein."; exit 1; }
[ "${#PW}" -ge 8 ] || { echo "Passwort zu kurz."; exit 1; }
printf '%s' "$BENUTZER" > "$DATEN/benutzer.txt"
printf '%s' "$PW" > "$DATEN/passwort.txt"
chmod 600 "$DATEN/benutzer.txt" "$DATEN/passwort.txt"
echo "Gespeichert. Gilt sofort, ein Neustart ist nicht nötig."
