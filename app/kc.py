"""Bewertungsfaktor (Kc) eines Heizkoerpers aus Typ, Hoehe und Laenge.

Naeherung nach der EN-442-Typenreihe (Watt je Meter Baulaenge bei 600 mm Bauhoehe,
Spreizung 75/65/20). Der kleinste Heizkoerper im Bestand erhaelt den Faktor 1,0.
Fuer eine pruefbare Abrechnung kann der Faktor je Heizkoerper in der Webseite
manuell ueberschrieben werden (z. B. aus einem Herstellerdatenblatt)."""

from __future__ import annotations

NORMLEISTUNG_600MM_W_PRO_M = {
    "10": 895,
    "11": 1145,
    "20": 1520,
    "21": 1765,
    "22": 2065,
    "30": 2140,
    "33": 2900,
}

HOEHENFAKTOR = {300: 0.72, 400: 0.82, 500: 0.91, 600: 1.00, 700: 1.08, 900: 1.22}

HKV_TYPEN = list(NORMLEISTUNG_600MM_W_PRO_M.keys())


def _hoehenfaktor(hoehe_cm: float) -> float:
    hoehe_mm = hoehe_cm * 10
    stuetz = sorted(HOEHENFAKTOR)
    if hoehe_mm <= stuetz[0]:
        return HOEHENFAKTOR[stuetz[0]]
    if hoehe_mm >= stuetz[-1]:
        return HOEHENFAKTOR[stuetz[-1]]
    for h1, h2 in zip(stuetz, stuetz[1:]):
        if h1 <= hoehe_mm <= h2:
            f1, f2 = HOEHENFAKTOR[h1], HOEHENFAKTOR[h2]
            return f1 + (hoehe_mm - h1) / (h2 - h1) * (f2 - f1)
    return 1.0


def normwaermeleistung_watt(typ: str, hoehe_cm: float, laenge_cm: float) -> float:
    typ = str(typ).strip()
    if typ not in NORMLEISTUNG_600MM_W_PRO_M:
        raise ValueError(f"Unbekannter Heizkoerpertyp '{typ}'")
    return NORMLEISTUNG_600MM_W_PRO_M[typ] * (laenge_cm / 100.0) * _hoehenfaktor(hoehe_cm)


def bewertungsfaktoren(heizkoerper: list[dict]) -> dict:
    """heizkoerper: [{'id', 'typ', 'hoehe_cm', 'laenge_cm'}] -> {id: faktor}, kleinster = 1,0."""
    leistungen = {}
    for hk in heizkoerper:
        try:
            leistungen[hk["id"]] = normwaermeleistung_watt(
                hk["typ"], float(hk["hoehe_cm"]), float(hk["laenge_cm"])
            )
        except (ValueError, TypeError, KeyError):
            continue
    if not leistungen:
        return {}
    kleinste = min(leistungen.values())
    if kleinste <= 0:
        return {}
    return {k: round(v / kleinste, 4) for k, v in leistungen.items()}
