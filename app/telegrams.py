"""Rohtelegramme aus dem wmbusmeters-Log lesen.

Mit logtelegrams=true schreibt wmbusmeters Zeilen der Form
    telegram=|1844AE4C4455223368077A55000000_041389E20100023B0000|+7
Aus dem Kopf (Laenge, C, Hersteller, Geraete-ID, Version, Medium) lesen wir die
Geraete-ID. So erkennt die Webseite auch Geraete, fuer die noch kein Schluessel
eingetragen ist ("Neu empfangen"-Liste)."""

from __future__ import annotations

import os
import re

TG_RE = re.compile(r"telegram=\|([0-9A-Fa-f_]+)\|(?:([+-]?\d+))?")


def hersteller_code(m: int) -> str:
    try:
        return "".join(chr(((m >> shift) & 0x1F) + 64) for shift in (10, 5, 0))
    except ValueError:
        return ""


def parse_telegram_hex(hexstr: str):
    """Kopf eines wM-Bus-Telegramms lesen. Gibt dict oder None zurueck."""
    h = hexstr.replace("_", "").strip()
    if len(h) < 20 or len(h) % 2:
        return None
    try:
        b = bytes.fromhex(h)
    except ValueError:
        return None
    m = b[2] | (b[3] << 8)
    geraet_id = "".join(f"{x:02X}" for x in reversed(b[4:8]))
    return {
        "geraet_id": geraet_id,
        "hersteller": hersteller_code(m),
        "version": b[8],
        "medium": b[9],
    }


def scan_new_lines(path: str, offset: int):
    """Neue Telegramm-Zeilen seit 'offset' lesen. Gibt (liste, neuer_offset) zurueck."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return [], offset
    if size < offset:  # Log wurde rotiert
        offset = 0
    if size == offset:
        return [], offset
    found = []
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read(size - offset)
    # nur vollstaendige Zeilen verarbeiten
    last_nl = data.rfind(b"\n")
    if last_nl == -1:
        return [], offset
    complete = data[: last_nl + 1]
    for line in complete.decode("utf-8", errors="replace").splitlines():
        m = TG_RE.search(line)
        if not m:
            continue
        parsed = parse_telegram_hex(m.group(1))
        if parsed is None:
            continue
        rssi = int(m.group(2)) if m.group(2) not in (None, "") else None
        parsed["rssi"] = rssi
        found.append(parsed)
    return found, offset + len(complete)
