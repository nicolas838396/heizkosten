"""Abrechnungsblatt je Wohnung als PDF."""

from __future__ import annotations

import datetime as dt

from .pdfmini import Pdf


def eur(x: float) -> str:
    s = f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


def zahl(x, nachkomma=2) -> str:
    if x is None:
        return "-"
    return f"{x:,.{nachkomma}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def datum(iso: str) -> str:
    if not iso:
        return ""
    try:
        return dt.date.fromisoformat(iso[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return iso


def wohnung_pdf(ergebnis: dict, wohnung_id: str, objekt: str, titel: str) -> bytes:
    zeile = next((w for w in ergebnis["wohnungen"] if w["id"] == wohnung_id), None)
    if zeile is None:
        raise KeyError(wohnung_id)
    pdf = Pdf()
    m = pdf.margin
    rechts = pdf.W - m

    pdf.text(m, pdf.y, titel, size=18, bold=True)
    pdf.y -= 22
    pdf.text(m, pdf.y, objekt, size=11, gray=0.3)
    pdf.y -= 16
    von, bis = ergebnis.get("von", ""), ergebnis.get("bis", "")
    zeitraum = f"{datum(von) or 'Beginn der Messung'} bis {datum(bis) or 'letzter Messwert'}"
    pdf.text(m, pdf.y, f"Abrechnungszeitraum: {zeitraum}", size=10, gray=0.3)
    pdf.y -= 8
    pdf.line(m, pdf.y, rechts, pdf.y)
    pdf.y -= 22

    pdf.text(m, pdf.y, f"{zeile['bezeichnung'] or zeile['id']}", size=13, bold=True)
    pdf.text(rechts, pdf.y, f"Wohnfläche: {zahl(zeile['flaeche_qm'])} m²", size=10, align="r")
    pdf.y -= 26

    # Ergebnisbox
    pdf.rect(m, pdf.y - 34, rechts - m, 44, fill=0.93)
    pdf.text(m + 12, pdf.y - 8, "Anteil an den Heizkosten", size=11)
    pdf.text(rechts - 12, pdf.y - 12, eur(zeile["kosten_gesamt"]), size=18, bold=True, align="r")
    pdf.y -= 56

    # Kostenaufteilung
    pdf.text(m, pdf.y, "Kostenaufteilung", size=11, bold=True)
    pdf.y -= 16
    zeilen = [
        ("Heizkosten gesamt (Haus)", eur(ergebnis["gesamtkosten"])),
        (f"davon Verbrauchskosten ({ergebnis['verbrauchsanteil']} %)", eur(ergebnis["verbrauchstopf"])),
        (f"davon Grundkosten ({100 - ergebnis['verbrauchsanteil']} %)", eur(ergebnis["grundtopf"])),
        ("", ""),
        (f"Ihr Anteil Verbrauch ({zahl(zeile['anteil_verbrauch_prozent'])} %)", eur(zeile["kosten_verbrauch"])),
        (f"Ihr Anteil Grundkosten nach Fläche ({zahl(zeile['anteil_flaeche_prozent'])} %)", eur(zeile["kosten_grund"])),
    ]
    for label, wert in zeilen:
        if label:
            pdf.text(m + 8, pdf.y, label, size=10)
            pdf.text(rechts, pdf.y, wert, size=10, align="r")
        pdf.y -= 14
    pdf.line(m, pdf.y + 8, rechts, pdf.y + 8)
    pdf.text(m + 8, pdf.y - 6, "Summe", size=10, bold=True)
    pdf.text(rechts, pdf.y - 6, eur(zeile["kosten_gesamt"]), size=10, bold=True, align="r")
    pdf.y -= 34

    # Geraete
    pdf.ensure(60)
    pdf.text(m, pdf.y, "Erfasster Verbrauch Ihrer Messgeräte", size=11, bold=True)
    pdf.y -= 16
    spalten = [m + 8, m + 150, rechts - 130, rechts - 70, rechts]
    kopf = ["Raum / Bezeichnung", "Gerät", "Verbrauch", "Faktor", "Einheiten"]
    for i, k in enumerate(kopf):
        pdf.text(spalten[i], pdf.y, k, size=9, bold=True, align="l" if i < 2 else "r", gray=0.25)
    pdf.y -= 4
    pdf.line(m, pdf.y, rechts, pdf.y)
    pdf.y -= 12
    for g in zeile["geraete"]:
        pdf.ensure(18)
        name = g["raum"] or g["bezeichnung"] or "-"
        if g["typ"] == "HKV":
            verbrauch = zahl(g.get("verbrauch"))
            faktor = zahl(g.get("kc"), 3)
            einheiten = zahl(g.get("einheiten"))
        else:
            verbrauch = f"{zahl(g.get('verbrauch'))} kWh"
            faktor, einheiten = "-", "-"
        pdf.text(spalten[0], pdf.y, name[:28], size=9)
        pdf.text(spalten[1], pdf.y, (g.get("geraet_id") or "nicht zugeordnet"), size=9)
        pdf.text(spalten[2], pdf.y, verbrauch, size=9, align="r")
        pdf.text(spalten[3], pdf.y, faktor, size=9, align="r")
        pdf.text(spalten[4], pdf.y, einheiten, size=9, align="r")
        pdf.y -= 13
    if not zeile["geraete"]:
        pdf.text(m + 8, pdf.y, "Dieser Wohnung sind keine Messgeräte zugeordnet.", size=9, gray=0.4)
        pdf.y -= 13
    pdf.y -= 12

    # Heizkreise
    if ergebnis["kreise"]:
        pdf.ensure(60)
        pdf.text(m, pdf.y, "Verteilung der Verbrauchskosten auf die Heizkreise (Haus)", size=11, bold=True)
        pdf.y -= 16
        for k in ergebnis["kreise"]:
            pdf.ensure(16)
            pdf.text(m + 8, pdf.y, f"Heizkreis {k['kreis']}: {zahl(k['kwh'])} kWh", size=9)
            pdf.text(rechts, pdf.y, eur(k["kosten"]), size=9, align="r")
            pdf.y -= 13
        pdf.y -= 12

    # Hinweise
    pdf.ensure(70)
    notizen = [
        "Aufteilung nach Heizkostenverordnung (HeizkostenV): Verbrauchsanteil 50 bis 70 Prozent, Rest nach Wohnfläche.",
        "Heizkostenverteiler-Einheiten = Messwert x Bewertungsfaktor des Heizkörpers.",
        "Die Kosten für Warmwasser sind in dieser Aufstellung nicht enthalten.",
    ]
    if ergebnis.get("warnungen"):
        pdf.text(m, pdf.y, "ENTWURF - bitte vor Versand prüfen:", size=9, bold=True, gray=0.5)
        pdf.y -= 13
        for w in ergebnis["warnungen"]:
            pdf.ensure(14)
            pdf.text(m + 8, pdf.y, "- " + w[:110], size=8, gray=0.4)
            pdf.y -= 11
        pdf.y -= 6
    for n in notizen:
        pdf.ensure(14)
        pdf.text(m, pdf.y, n, size=8, gray=0.45)
        pdf.y -= 11
    pdf.text(m, m - 10, f"Erstellt am {dt.date.today().strftime('%d.%m.%Y')}", size=8, gray=0.5)
    return pdf.tobytes()
