"""SQLite-Datenhaltung: Wohnungen, Plaetze (Heizkostenverteiler / Waermemengenzaehler),
empfangene Geraete und Messwerte. Alles wird ueber die Webseite bearbeitet."""

from __future__ import annotations

import datetime as dt
import os
import sqlite3

DATA_DIR = os.environ.get(
    "HEIZKOSTEN_DATA",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS wohnung (
    id TEXT PRIMARY KEY,
    bezeichnung TEXT NOT NULL DEFAULT '',
    flaeche_qm REAL,
    nutzung TEXT NOT NULL DEFAULT '',
    sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS platz (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    typ TEXT NOT NULL CHECK (typ IN ('HKV', 'WMZ')),
    wohnung_id TEXT REFERENCES wohnung(id) ON DELETE SET NULL ON UPDATE CASCADE,
    raum TEXT NOT NULL DEFAULT '',
    bezeichnung TEXT NOT NULL DEFAULT '',
    heizkreis TEXT NOT NULL DEFAULT '1',
    hkv_typ TEXT NOT NULL DEFAULT '',
    hoehe_cm REAL,
    laenge_cm REAL,
    kc_manuell REAL,
    leistung_w REAL,
    fest_key TEXT UNIQUE,
    geraet_id TEXT UNIQUE,
    aes_key TEXT NOT NULL DEFAULT '',
    notiz TEXT NOT NULL DEFAULT '',
    erstellt TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS gesehen (
    geraet_id TEXT PRIMARY KEY,
    hersteller TEXT NOT NULL DEFAULT '',
    version INTEGER,
    medium INTEGER,
    erste TEXT NOT NULL,
    zuletzt TEXT NOT NULL,
    anzahl INTEGER NOT NULL DEFAULT 1,
    rssi INTEGER
);
CREATE TABLE IF NOT EXISTS messung (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    geraet_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    wert REAL NOT NULL,
    einheit TEXT NOT NULL DEFAULT '',
    quelle TEXT NOT NULL DEFAULT 'funk',
    UNIQUE (geraet_id, ts, quelle)
);
CREATE INDEX IF NOT EXISTS idx_messung ON messung (geraet_id, ts);
CREATE TABLE IF NOT EXISTS letzte (
    geraet_id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    roh TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS zaehler (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    art TEXT NOT NULL CHECK (art IN ('WARM', 'KALT', 'WW_WAERME')),
    wohnung_id TEXT REFERENCES wohnung(id) ON DELETE SET NULL ON UPDATE CASCADE,
    bezeichnung TEXT NOT NULL DEFAULT '',
    einheit TEXT NOT NULL DEFAULT 'm³',
    notiz TEXT NOT NULL DEFAULT '',
    erstellt TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ablesung (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zaehler_id INTEGER NOT NULL REFERENCES zaehler(id) ON DELETE CASCADE,
    datum TEXT NOT NULL,
    wert REAL NOT NULL,
    foto TEXT NOT NULL DEFAULT '',
    notiz TEXT NOT NULL DEFAULT '',
    erstellt TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ablesung ON ablesung (zaehler_id, datum);
"""

DEFAULT_WOHNUNGEN = [
    ("EG", "Erdgeschoss", 1),
    ("1OG", "1. Obergeschoss", 2),
    ("DG", "Dachgeschoss", 3),
    ("KELLER", "Kellergeschoss", 4),
]

DEFAULT_SETTINGS = {
    "gesamtkosten": "",
    "wasserkosten": "",
    "verbrauchsanteil": "50",
    "ww_verbrauchsanteil": "70",
    "ww_temperatur": "60",
    "ww_pauschal_prozent": "",
    "abrechnung_von": "",
    "abrechnung_bis": "",
    "abrechnung_titel": "Heiz- und Wasserkostenabrechnung",
    "objekt": "Mehrfamilienhaus Erlabrunn",
    "device": "/dev/ttyACM0:iu891a:t1,c1",
}


ZAEHLER_ARTEN = {
    "WARM": "Warmwasserzähler",
    "KALT": "Kaltwasserzähler",
    "WW_WAERME": "Wärmemengenzähler Warmwasser (abgelesen)",
}


def foto_dir() -> str:
    return os.path.join(DATA_DIR, "demo-fotos" if demo_active() else "fotos")


def now_iso() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def demo_flag_path() -> str:
    return os.path.join(DATA_DIR, "demo.flag")


def demo_active() -> bool:
    return os.path.exists(demo_flag_path())


def set_demo(active: bool) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    if active:
        with open(demo_flag_path(), "w") as f:
            f.write("1")
    elif demo_active():
        os.remove(demo_flag_path())


def fest_aktiv() -> bool:
    """Feste Stammdaten aktiv (Normalbetrieb). Demo und HEIZKOSTEN_STAMMDATEN=0 schalten sie ab."""
    return not demo_active() and os.environ.get("HEIZKOSTEN_STAMMDATEN", "1") != "0"


def db_path() -> str:
    return os.path.join(DATA_DIR, "demo.db" if demo_active() else "heizkosten.db")


def connect() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    path = db_path()
    fresh = not os.path.exists(path)
    con = sqlite3.connect(path, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    _migrate(con)
    if fresh:
        _seed_defaults(con, demo=demo_active())
    if fest_aktiv():
        from . import stammdaten

        stammdaten.sync(con)
    con.commit()
    return con


def _migrate(con: sqlite3.Connection) -> None:
    """Aeltere Datenbanken um neue Spalten ergaenzen."""
    spalten = {r["name"] for r in con.execute("PRAGMA table_info(platz)")}
    if "leistung_w" not in spalten:
        con.execute("ALTER TABLE platz ADD COLUMN leistung_w REAL")
    if "fest_key" not in spalten:
        con.execute("ALTER TABLE platz ADD COLUMN fest_key TEXT")
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_platz_fest ON platz (fest_key)")


def _seed_defaults(con: sqlite3.Connection, demo: bool) -> None:
    for key, value in DEFAULT_SETTINGS.items():
        con.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
    if demo:
        from . import demo as demo_mod

        demo_mod.fill(con)
        return
    for wid, bez, sort in DEFAULT_WOHNUNGEN:
        con.execute(
            "INSERT OR IGNORE INTO wohnung (id, bezeichnung, sort) VALUES (?, ?, ?)",
            (wid, bez, sort),
        )


def get_setting(con: sqlite3.Connection, key: str, default: str = "") -> str:
    row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None or row["value"] is None:
        return DEFAULT_SETTINGS.get(key, default)
    return row["value"]


def set_setting(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def normalize_id(raw: str) -> str:
    """Geraete-Nummer vereinheitlichen: Leerzeichen weg, auf 8 Stellen auffuellen, Grossbuchstaben."""
    s = "".join(ch for ch in (raw or "") if ch.isalnum()).upper()
    if not s:
        return ""
    return s.zfill(8) if len(s) < 8 else s


def normalize_key(raw: str) -> str:
    """AES-Schluessel: nur Hex-Zeichen, Grossbuchstaben (32 Zeichen erwartet)."""
    return "".join(ch for ch in (raw or "") if ch in "0123456789abcdefABCDEF").upper()
