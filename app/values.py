"""Messwert aus dem JSON eines wmbusmeters-Telegramms herausziehen.

wmbusmeters benennt die Felder je nach Treiber leicht unterschiedlich. Diese Funktion
sucht zuerst nach bekannten Namen und faellt sonst auf eine Heuristik zurueck. Welches
Feld genommen wurde, zeigt die Webseite je Geraet an (Rohdaten), damit man es bei Bedarf
pruefen kann."""

from __future__ import annotations

# (Feldname, Umrechnungsfaktor nach kWh)
WMZ_FELDER = [
    ("total_energy_consumption_kwh", 1.0),
    ("total_heat_energy_kwh", 1.0),
    ("total_energy_kwh", 1.0),
    ("energy_kwh", 1.0),
    ("total_energy_consumption_mwh", 1000.0),
    ("total_energy_consumption_gj", 277.7778),
    ("total_energy_consumption_mj", 0.2777778),
]

HKV_FELDER = [
    "current_consumption_hca",
    "total_consumption_hca",
    "consumption_hca",
    "current_consumption",
    "total_consumption",
]


def _zahl(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def extract_value(typ: str, data: dict):
    """Gibt (wert, einheit, feldname) zurueck oder (None, None, None)."""
    if not isinstance(data, dict):
        return None, None, None

    if typ == "WMZ":
        for key, faktor in WMZ_FELDER:
            if key in data and _zahl(data[key]) is not None:
                return _zahl(data[key]) * faktor, "kWh", key
        for key, v in data.items():
            low = key.lower()
            if "energy" in low and low.endswith("_kwh") and _zahl(v) is not None:
                return _zahl(v), "kWh", key
        return None, None, None

    for key in HKV_FELDER:
        if key in data and _zahl(data[key]) is not None:
            return _zahl(data[key]), "Einheiten", key
    for key, v in data.items():
        low = key.lower()
        if "hca" in low and "date" not in low and "temp" not in low and _zahl(v) is not None:
            return _zahl(v), "Einheiten", key
    return None, None, None
