#!/usr/bin/env bash
# Richtet einen eingeschraenkten Benutzer samt eigenem Dienst fuer ein zweites Programm ein.
# Aufruf: bash deploy/gast.sh <name> [port]      (z. B. bash deploy/gast.sh domi 8080)
#
# Der Gast kann: sich per SSH anmelden, in seinem Ordner programmieren, Pakete in seinem
# Ordner installieren (pip/npm), seinen eigenen Dienst starten/stoppen/neu starten und dessen Log lesen.
# Der Gast kann NICHT: sudo allgemein nutzen, die Heizungs-App, ihre Daten oder Passwoerter
# lesen/aendern/loeschen, Dienste des Besitzers anhalten, Ports unter 1024 belegen.
set -euo pipefail

NAME="${1:-}"
PORT="${2:-8080}"
if [[ -z "$NAME" || ! "$NAME" =~ ^[a-z][a-z0-9_-]{1,20}$ ]]; then
  echo "Aufruf: bash deploy/gast.sh <name> [port]   (Name: Kleinbuchstaben/Ziffern)"; exit 1
fi
if [[ "$PORT" -lt 1024 || "$PORT" -gt 65535 || "$PORT" == "80" ]]; then
  echo "Port muss zwischen 1024 und 65535 liegen."; exit 1
fi
BESITZER="${SUDO_USER:-$USER}"
if [[ "$NAME" == "$BESITZER" || "$NAME" == "root" ]]; then echo "Name ist schon vergeben."; exit 1; fi
UNIT="gast-$NAME"

# 1. Benutzer anlegen (ohne Administratorrechte)
if ! id "$NAME" >/dev/null 2>&1; then
  sudo adduser --disabled-password --gecos "" "$NAME"
fi
sudo gpasswd -d "$NAME" sudo 2>/dev/null || true
sudo chmod 750 "/home/$NAME"

# 2. Heizungs-App und ihre Daten vor dem Gast verschliessen
sudo chmod 700 "/home/$BESITZER"
[ -d /var/lib/heizkosten ] && sudo chmod -R go-rwx /var/lib/heizkosten

# 3. Start-Skript des Gastes (das darf er selbst aendern, ohne Root)
sudo -u "$NAME" mkdir -p "/home/$NAME/app"
if [ ! -f "/home/$NAME/start.sh" ]; then
  sudo -u "$NAME" tee "/home/$NAME/start.sh" >/dev/null <<EOS
#!/usr/bin/env bash
# Dieses Skript startet dein Programm. Es soll auf dem Port \$PORT lauschen.
# Beispiel Python:  cd ~/app && exec ./venv/bin/python app.py
cd ~/app
exec python3 -m http.server \$PORT
EOS
  sudo chmod 755 "/home/$NAME/start.sh"
fi

# 4. Eigener Dienst mit Ressourcengrenzen, damit die Heizung nie ausgebremst wird
sudo tee "/etc/systemd/system/$UNIT.service" >/dev/null <<EOS
[Unit]
Description=Programm von $NAME
After=network-online.target

[Service]
User=$NAME
Group=$NAME
WorkingDirectory=/home/$NAME
Environment=PORT=$PORT
ExecStart=/home/$NAME/start.sh
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
MemoryMax=180M
CPUQuota=60%
TasksMax=100

[Install]
WantedBy=multi-user.target
EOS
sudo systemctl daemon-reload
sudo systemctl enable "$UNIT" >/dev/null

# 5. Genau diese Befehle darf der Gast mit sudo, sonst nichts
SUDOERS="/etc/sudoers.d/$UNIT"
{
  for aktion in start stop restart status; do
    echo "$NAME ALL=(root) NOPASSWD: /usr/bin/systemctl $aktion $UNIT"
  done
  echo "$NAME ALL=(root) NOPASSWD: /usr/bin/journalctl -u $UNIT --no-pager -n *"
} | sudo tee "$SUDOERS" >/dev/null
sudo chmod 440 "$SUDOERS"
sudo visudo -cf "$SUDOERS" >/dev/null

sudo systemctl restart "$UNIT"

IP=$(hostname -I | awk '{print $1}')
cat <<EOM

Fertig. Benutzer: $NAME   Dienst: $UNIT   Port: $PORT

Noch zu tun (einmalig):
  sudo passwd $NAME          # Passwort fuer den Gast setzen und ihm geben
Anmeldung des Gastes:      ssh $NAME@$IP
Sein Programm im Browser:  http://$IP:$PORT   (vorerst ein Platzhalter-Server)
Sein Programm (neu) starten: sudo systemctl restart $UNIT
Log ansehen:               sudo journalctl -u $UNIT --no-pager -n 50
Dein Programm bleibt unberuehrt (Dienst heizkosten, Port 80).
EOM
