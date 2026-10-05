"""Schnellerfassung: Plaetze aus einer Freitext-Liste anlegen.

Beispiel:
    EG: Wohnzimmer 2, Kueche 1, Bad 1
    1. OG: Wohnzimmer 2, Schlafzimmer
Eine Zahl hinter dem Raum ist die Anzahl der Heizkoerper (ohne Zahl = 1)."""

from __future__ import annotations

import re

_RAUM = re.compile(r"^(.*?)(?:\s+(\d{1,2}))?$")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss"))


def finde_wohnung(label: str, wohnungen: list):
    """wohnungen: [{'id','bezeichnung'}]. Gibt die id zurueck oder None."""
    n = _norm(label)
    if not n:
        return None
    for w in wohnungen:
        if _norm(w["id"]) == n or _norm(w.get("bezeichnung", "")) == n:
            return w["id"]
    for w in wohnungen:  # lockerer: "erdgeschoss" passt auf "Erdgeschoss", "og1" ...
        bez = _norm(w.get("bezeichnung", ""))
        if bez and (n in bez or bez in n):
            return w["id"]
    return None


def neue_wohnungs_id(label: str, vorhandene: set) -> str:
    basis = re.sub(r"[^A-Za-z0-9]", "", label.upper())[:10] or "WOHNUNG"
    kandidat, i = basis, 2
    while kandidat in vorhandene:
        kandidat = f"{basis}{i}"
        i += 1
    return kandidat


def parse(text: str) -> list:
    """Gibt [(wohnung_label, raum, anzahl), ...] zurueck."""
    ergebnis = []
    for zeile in (text or "").splitlines():
        zeile = zeile.strip()
        if not zeile or ":" not in zeile:
            continue
        label, rest = zeile.split(":", 1)
        label = label.strip()
        if not label:
            continue
        for teil in re.split(r"[,;]", rest):
            teil = teil.strip()
            if not teil:
                continue
            m = _RAUM.match(teil)
            raum = (m.group(1) or "").strip()
            anzahl = int(m.group(2)) if m.group(2) else 1
            if raum:
                ergebnis.append((label, raum, max(1, min(anzahl, 20))))
    return ergebnis
