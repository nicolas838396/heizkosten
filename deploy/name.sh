#!/usr/bin/env bash
# Gibt dem Pi einen kurzen Namen. Danach: http://<name>.local
# Aufruf:  bash deploy/name.sh heizung
set -euo pipefail
NAME="${1:?Bitte Namen angeben, z. B. heizung}"
sudo hostnamectl set-hostname "$NAME"
sudo sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$NAME/" /etc/hosts
grep -q "^127.0.1.1" /etc/hosts || echo -e "127.0.1.1\t$NAME" | sudo tee -a /etc/hosts >/dev/null
sudo systemctl enable --now avahi-daemon >/dev/null 2>&1 || true
sudo systemctl restart avahi-daemon || true
echo "Fertig. Der Pi heißt jetzt $NAME und ist erreichbar unter http://$NAME.local"
