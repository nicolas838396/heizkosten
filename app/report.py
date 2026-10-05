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
    wa = ergebnis["wasser"]
    pdf = Pdf()
    m = pdf.margin
    rechts = pdf.W - m

    def zeile_lr(label, wert, bold=False, size=10, einzug=8):
        pdf.ensure(16)
        pdf.text(m + einzug, pdf.y, label, size=size, bold=bold)
        pdf.text(rechts, pdf.y, wert, size=size, bold=bold, align="r")
        pdf.y -= 14

    def abschnitt(text):
        pdf.ensure(50)
        pdf.y -= 6
        pdf.text(m, pdf.y, text, size=12, bold=True)
        pdf.y -= 4
        pdf.line(m, pdf.y, rechts, pdf.y)
        pdf.y -= 16

    def unter(text):
        pdf.ensure(40)
        pdf.text(m, pdf.y, text, size=10, bold=True, gray=0.25)
        pdf.y -= 15

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
    pdf.text(m + 12, pdf.y - 8, "Ihr Gesamtbetrag", size=11)
    pdf.text(rechts - 12, pdf.y - 12, eur(zeile["summe_gesamt"]), size=18, bold=True, align="r")
    pdf.y -= 58

    zeile_lr("1. Heizung", eur(zeile["heizung_gesamt"]))
    zeile_lr("2. Warmwasser", eur(zeile["ww_gesamt"]))
    zeile_lr("3. Kaltwasser", eur(zeile["kalt_kosten"]))
    pdf.line(m, pdf.y + 8, rechts, pdf.y + 8)
    pdf.y -= 2
    zeile_lr("Summe", eur(zeile["summe_gesamt"]), bold=True)
    pdf.y -= 8

    # ---- 1. Heizung
    abschnitt("1. Heizung")
    unter("Kostenaufteilung")
    zeile_lr("Heizkosten (Haus, ohne Warmwasser)", eur(ergebnis["gesamtkosten"]))
    zeile_lr(f"davon Verbrauchskosten ({ergebnis['verbrauchsanteil']} %)", eur(ergebnis["verbrauchstopf"]))
    zeile_lr(f"davon Grundkosten ({100 - ergebnis['verbrauchsanteil']} %)", eur(ergebnis["grundtopf"]))
    zeile_lr(f"Ihr Anteil Verbrauch ({zahl(zeile['anteil_verbrauch_prozent'])} %)", eur(zeile["kosten_verbrauch"]))
    zeile_lr(f"Ihr Anteil Grundkosten nach Fläche ({zahl(zeile['anteil_flaeche_prozent'])} %)", eur(zeile["kosten_grund"]))
    pdf.line(m, pdf.y + 8, rechts, pdf.y + 8)
    pdf.y -= 2
    zeile_lr("Summe Heizung", eur(zeile["heizung_gesamt"]), bold=True)
    pdf.y -= 8

    pdf.ensure(60)
    unter("Erfasster Verbrauch Ihrer Heizkörper-Messgeräte")
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
    pdf.y -= 8

    if ergebnis["kreise"]:
        pdf.ensure(40)
        unter("Verteilung der Verbrauchskosten auf die Heizkreise (Haus)")
        for k in ergebnis["kreise"]:
            zeile_lr(f"Heizkreis {k['kreis']}: {zahl(k['kwh'])} kWh", eur(k["kosten"]), size=9)
        pdf.y -= 6

    # ---- 2. Warmwasser
    abschnitt("2. Warmwasser")
    unter("Haus")
    zeile_lr(f"Wärmemenge Warmwasser ({wa['ww_quelle']})", f"{zahl(wa['ww_kwh'], 0)} kWh", size=9)
    zeile_lr("Energiekosten Warmwasser (Anteil an der Heizenergie nach Wärmemenge)", eur(wa["ww_energie"]), size=9)
    zeile_lr(f"davon Verbrauchskosten ({wa['ww_verbrauchsanteil']} %, nach Warmwasser-m³)", eur(wa["ww_verbrauchstopf"]), size=9)
    zeile_lr(f"davon Grundkosten ({100 - wa['ww_verbrauchsanteil']} %, nach Wohnfläche)", eur(wa["ww_grundtopf"]), size=9)
    zeile_lr(f"Warmwasserverbrauch Haus: {zahl(wa['m3_warm'], 3)} m³", "", size=9)
    pdf.y -= 6
    unter("Ihr Anteil")
    zeile_lr("Energie nach Verbrauch", eur(zeile["ww_energie_verbrauch"]))
    zeile_lr("Energie Grundkosten", eur(zeile["ww_energie_grund"]))
    zeile_lr(f"Wasser/Abwasser für Warmwasser ({zahl(zeile['m3_warm'], 3)} m³ × {zahl(wa['preis_m3'])} €)", eur(zeile["ww_wasser"]))
    pdf.line(m, pdf.y + 8, rechts, pdf.y + 8)
    pdf.y -= 2
    zeile_lr("Summe Warmwasser", eur(zeile["ww_gesamt"]), bold=True)
    pdf.y -= 8

    # ---- 3. Kaltwasser
    abschnitt("3. Kaltwasser")
    zeile_lr(f"Wasser- und Abwasserpreis (Haus gesamt {eur(wa['wasserkosten'])})", f"{zahl(wa['preis_m3'])} € / m³", size=9)
    zeile_lr(f"Ihr Kaltwasserverbrauch: {zahl(zeile['m3_kalt'], 3)} m³", eur(zeile["kalt_kosten"]))
    pdf.line(m, pdf.y + 8, rechts, pdf.y + 8)
    pdf.y -= 2
    zeile_lr("Summe Kaltwasser", eur(zeile["kalt_kosten"]), bold=True)
    pdf.y -= 8

    # ---- Wasserzaehler
    pdf.ensure(60)
    unter("Wasserzähler Ihrer Wohnung (abgelesen)")
    sp = [m + 8, m + 190, m + 280, rechts - 70, rechts]
    for i, k in enumerate(["Zähler", "Art", "Anfang", "Ende", "Verbrauch"]):
        pdf.text(sp[i], pdf.y, k, size=9, bold=True, align="l" if i < 2 else "r", gray=0.25)
    pdf.y -= 4
    pdf.line(m, pdf.y, rechts, pdf.y)
    pdf.y -= 12
    for q in zeile["zaehler"]:
        pdf.ensure(28)
        pdf.text(sp[0], pdf.y, (q.get("bezeichnung") or f"Zähler {q['id']}")[:32], size=9)
        pdf.text(sp[1], pdf.y, "Warmwasser" if q["art"] == "WARM" else "Kaltwasser", size=9)
        pdf.text(sp[2], pdf.y, zahl(q["start"][1], 3) if q.get("start") else "-", size=9, align="r")
        pdf.text(sp[3], pdf.y, zahl(q["ende"][1], 3) if q.get("ende") else "-", size=9, align="r")
        pdf.text(sp[4], pdf.y, f"{zahl(q.get('verbrauch'), 3)} m³" if q.get("verbrauch") is not None else "-", size=9, align="r")
        pdf.y -= 11
        if q.get("start") and q.get("ende"):
            pdf.text(sp[0], pdf.y, f"abgelesen {datum(q['start'][0])} / {datum(q['ende'][0])}", size=7, gray=0.5)
            pdf.y -= 10
        else:
            pdf.y -= 2
    if not zeile["zaehler"]:
        pdf.text(m + 8, pdf.y, "Dieser Wohnung sind keine Wasserzähler zugeordnet.", size=9, gray=0.4)
        pdf.y -= 13
    pdf.y -= 10

    # Hinweise
    pdf.ensure(70)
    notizen = [
        "Aufteilung nach Heizkostenverordnung (HeizkostenV): Verbrauchsanteil 50 bis 70 Prozent, Rest nach Wohnfläche.",
        "Heizkostenverteiler-Einheiten = Messwert x Bewertungsfaktor des Heizkörpers.",
        "Warmwasserenergie: Anteil an den Heizenergiekosten nach gemessener Wärmemenge (§ 9 HeizkostenV).",
        "Wasser und Abwasser werden mit einem einheitlichen Preis je m³ auf Kalt- und Warmwasser verteilt.",
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
