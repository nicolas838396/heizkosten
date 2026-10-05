"""Konfiguration fuer wmbusmeters aus den Plaetzen der Webseite erzeugen.

Je zugeordnetem Geraet entsteht eine Datei im Ordner meters.d (der per Symlink als
/etc/wmbusmeters.d eingebunden ist). Danach wird der Dienst neu gestartet."""

from __future__ import annotations

import os
import subprocess

METERS_DIR = os.environ.get("WMBUS_METERS_DIR", "/var/lib/heizkosten/meters.d")
MAIN_CONF = os.environ.get("WMBUS_MAIN_CONF", "/etc/wmbusmeters.conf")


def meter_datei_inhalt(geraet_id: str, key: str) -> str:
    return (
        f"name=g{geraet_id}\n"
        f"id={geraet_id}\n"
        "driver=auto\n"
        f"key={key if key else 'NOKEY'}\n"
    )


def write_meter_files(con, folder: str | None = None) -> dict:
    folder = folder or METERS_DIR
    os.makedirs(folder, exist_ok=True)
    rows = con.execute(
        "SELECT geraet_id, aes_key FROM platz WHERE geraet_id IS NOT NULL AND geraet_id != ''"
    ).fetchall()
    soll = {}
    for r in rows:
        soll[f"g{r['geraet_id']}"] = meter_datei_inhalt(r["geraet_id"], r["aes_key"])
    for name in os.listdir(folder):
        pfad = os.path.join(folder, name)
        if os.path.isfile(pfad) and name.startswith("g") and name not in soll:
            os.remove(pfad)
    for name, inhalt in soll.items():
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write(inhalt)
    ohne_key = [r["geraet_id"] for r in rows if not r["aes_key"]]
    return {"anzahl": len(soll), "ohne_schluessel": ohne_key}


def restart_service() -> tuple[bool, str]:
    try:
        res = subprocess.run(
            ["sudo", "-n", "systemctl", "restart", "wmbusmeters"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if res.returncode != 0:
        return False, (res.stderr or res.stdout or "unbekannter Fehler").strip()
    return True, "wmbusmeters neu gestartet"


def service_status() -> str:
    try:
        res = subprocess.run(
            ["systemctl", "is-active", "wmbusmeters"], capture_output=True, text=True, timeout=10
        )
        return (res.stdout or "").strip() or "unbekannt"
    except (OSError, subprocess.SubprocessError):
        return "unbekannt"
