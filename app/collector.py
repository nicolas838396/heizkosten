"""Sammelt Daten von wmbusmeters in die Datenbank:

1. Telegramm-Log  -> Tabelle 'gesehen' (alle Geraete, die der Stick hoert; "Neu empfangen")
2. meter_readings -> Tabelle 'messung'/'letzte' (entschluesselte Werte der zugeordneten Geraete)

Laeuft als Hintergrund-Thread in der Webseite (alle 30 Sekunden)."""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time

from . import db, telegrams, values

LOG_PATH = os.environ.get("WMBUS_LOG", "/var/log/wmbusmeters/wmbusmeters.log")
METER_DIR = os.environ.get("WMBUS_METERFILES", "/var/lib/wmbusmeters/meter_readings")

status = {
    "letzter_lauf": None,
    "log_ok": None,
    "log_fehler": "",
    "meter_ok": None,
    "meter_fehler": "",
}

_lock = threading.Lock()


def note_seen(con, geraet_id, hersteller="", version=None, medium=None, rssi=None, ts=None):
    ts = ts or db.now_iso()
    row = con.execute("SELECT anzahl, zuletzt FROM gesehen WHERE geraet_id = ?", (geraet_id,)).fetchone()
    if row is None:
        con.execute(
            "INSERT INTO gesehen (geraet_id, hersteller, version, medium, erste, zuletzt, anzahl, rssi) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (geraet_id, hersteller, version, medium, ts, ts, rssi),
        )
    else:
        zuletzt = max(row["zuletzt"], ts)
        con.execute(
            "UPDATE gesehen SET zuletzt = ?, anzahl = anzahl + 1, rssi = COALESCE(?, rssi), "
            "hersteller = CASE WHEN ? != '' THEN ? ELSE hersteller END WHERE geraet_id = ?",
            (zuletzt, rssi, hersteller, hersteller, geraet_id),
        )


def scan_log(con, path=None):
    path = path or LOG_PATH
    if not os.path.exists(path):
        status["log_ok"] = False
        status["log_fehler"] = f"Log-Datei nicht gefunden: {path}"
        return 0
    if not os.access(path, os.R_OK):
        status["log_ok"] = False
        status["log_fehler"] = f"Keine Leseberechtigung fuer {path}"
        return 0
    offset = int(db.get_setting(con, "log_offset", "0") or 0)
    lines, new_offset = telegrams.scan_new_lines(path, offset)
    for t in lines:
        note_seen(con, t["geraet_id"], t["hersteller"], t["version"], t["medium"], t["rssi"])
    db.set_setting(con, "log_offset", str(new_offset))
    status["log_ok"] = True
    status["log_fehler"] = ""
    return len(lines)


def _utc_to_local_iso(ts: str) -> str:
    try:
        d = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if d.tzinfo is not None:
            d = d.astimezone().replace(tzinfo=None)
        return d.replace(microsecond=0).isoformat()
    except (ValueError, AttributeError):
        return db.now_iso()


def scan_meterfiles(con, folder=None):
    folder = folder or METER_DIR
    if not os.path.isdir(folder):
        status["meter_ok"] = False
        status["meter_fehler"] = f"Messwert-Ordner nicht gefunden: {folder}"
        return 0
    neu = 0
    for name in sorted(os.listdir(folder)):
        pfad = os.path.join(folder, name)
        if not os.path.isfile(pfad):
            continue
        try:
            with open(pfad, encoding="utf-8") as f:
                zeilen = [z.strip() for z in f if z.strip()]
            data = json.loads(zeilen[-1]) if zeilen else None
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        geraet_id = db.normalize_id(str(data.get("id", ""))) or db.normalize_id(name.lstrip("gG"))
        platz = con.execute("SELECT typ FROM platz WHERE geraet_id = ?", (geraet_id,)).fetchone()
        ts = _utc_to_local_iso(str(data.get("timestamp", "")))
        con.execute(
            "INSERT INTO letzte (geraet_id, ts, roh) VALUES (?, ?, ?) "
            "ON CONFLICT(geraet_id) DO UPDATE SET ts = excluded.ts, roh = excluded.roh",
            (geraet_id, ts, json.dumps(data, ensure_ascii=False)),
        )
        if platz is None:
            continue
        wert, einheit, _feld = values.extract_value(platz["typ"], data)
        if wert is None:
            continue
        cur = con.execute(
            "INSERT OR IGNORE INTO messung (geraet_id, ts, wert, einheit, quelle) VALUES (?, ?, ?, ?, 'funk')",
            (geraet_id, ts, wert, einheit),
        )
        if cur.rowcount:
            neu += 1
            note_seen(con, geraet_id, ts=ts)
    status["meter_ok"] = True
    status["meter_fehler"] = ""
    return neu


def run_once():
    with _lock:
        con = db.connect()
        try:
            scan_log(con)
            scan_meterfiles(con)
            con.commit()
        finally:
            con.close()
        status["letzter_lauf"] = db.now_iso()


def start_background(interval=30):
    def loop():
        while True:
            try:
                run_once()
            except Exception as exc:  # noqa: BLE001 - Hintergrundthread darf nie sterben
                status["log_fehler"] = f"Fehler im Sammler: {exc}"
            time.sleep(interval)

    t = threading.Thread(target=loop, name="collector", daemon=True)
    t.start()
    return t
