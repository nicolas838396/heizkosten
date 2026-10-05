# Heizkosten Erlabrunn

Selbst gehostete Webseite auf dem Raspberry Pi: empfängt per Funk (wM-Bus, IMST iU893A-Stick + wmbusmeters)
die Heizkostenverteiler und Wärmemengenzähler, zeigt den Gerätestatus und erstellt die Heizkostenabrechnung
nach HeizkostenV als PDF je Wohnung. Keine laufenden Kosten, keine Cloud.

## Installation auf dem Pi

```bash
git clone https://github.com/nicolas838396/heizkosten.git
cd heizkosten
bash deploy/install.sh
```

Am Ende zeigt das Skript Adresse und Passwort an. Aufruf im Browser: `http://<Pi-IP>`.

Hinweis: Läuft die Installation im Raspberry-Pi-Connect-Browserterminal, kann die Verbindung kurz
abbrechen. Dann stattdessen: `sudo systemd-run --unit=hk-install --collect --working-directory=$PWD bash deploy/install.sh`
und das Ergebnis mit `sudo journalctl -u hk-install --no-pager | tail -20` ansehen.

## Aufbau

- `app/` Flask-Anwendung (SQLite in `/var/lib/heizkosten`), Sammler-Thread liest alle 30 s Log und Messwertdateien
- `deploy/` Installationsskript und systemd-Vorlage
- Demo-Modus: unter Einstellungen einschaltbar, nutzt eine getrennte Datenbank mit Beispieldaten

## Tests

```bash
python3 -m unittest discover -s tests -t .
```
