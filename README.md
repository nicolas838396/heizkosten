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

## Ablauf einer Abrechnung

1. Abrechnung: Heizenergie- und Wasserkosten sowie Zeitraum eintragen.
2. Zähler ablesen: je Wasserzähler Foto machen und Stand eintippen (Anfangs- und Endstand mit jeweiligem Datum).
3. Ergebnis: Heizung, Warmwasser und Kaltwasser je Wohnung, dazu ein PDF je Wohnung.

Wärmemengenzähler für das Warmwasser: als Platz mit Heizkreis `WW` anlegen (Funk), bis dahin als abgelesener Zähler.

## Aufbau

- `app/` Flask-Anwendung (SQLite in `/var/lib/heizkosten`), Sammler-Thread liest alle 30 s Log und Messwertdateien
- `deploy/` Installationsskript und systemd-Vorlage
- Demo-Modus: unter Einstellungen einschaltbar, nutzt eine getrennte Datenbank mit Beispieldaten

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

## Zweiter Benutzer fuer ein weiteres Programm

```
cd ~/heizkosten && git pull
bash deploy/gast.sh bruder 8080
sudo passwd bruder
```
Der Benutzer hat keine Administratorrechte, kann die Heizungs-App und ihre Daten nicht sehen
und darf nur seinen eigenen Dienst `gast-bruder` starten, stoppen und neu starten.
