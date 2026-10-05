"""Kostenaufteilung nach Heizkostenverordnung (HeizkostenV).

Modell
------
* Gesamtkosten werden in Verbrauchskosten (50-70 %) und Grundkosten (Rest) geteilt.
* Grundkosten: nach Wohnflaeche.
* Verbrauchskosten: je Heizkreis nach Waermemenge (kWh, Waermemengenzaehler) auf die Heizkreise
  verteilt; innerhalb eines Heizkreises nach Heizkostenverteiler-Einheiten (Rohwert x
  Bewertungsfaktor Kc) auf die Wohnungen. Hat ein Heizkreis keine Verteiler (z. B. Fussboden-
  heizung mit eigenem Waermemengenzaehler), geht sein Anteil an die Wohnung, die dem Zaehler
  zugeordnet ist.
* Fehlen Waermemengenzaehler-Daten ganz, werden die Verbrauchskosten allein nach
  Verteiler-Einheiten verteilt (Hinweis in den Warnungen).

Die Rechnung ist eine Hilfe zur Abrechnung und ersetzt keine rechtliche Pruefung."""

from __future__ import annotations

from . import db
from .kc import bewertungsfaktoren


def runden_summe(teile: dict, gesamt: float) -> dict:
    """Auf Cent runden, so dass die Summe exakt 'gesamt' (auf Cent) ergibt (Restcent-Verfahren)."""
    ziel = round(gesamt * 100)
    if not teile:
        return {}
    basis = {k: int(v * 100) for k, v in teile.items()}  # abgerundet
    rest = ziel - sum(basis.values())
    reihenfolge = sorted(teile, key=lambda k: (teile[k] * 100 - basis[k]), reverse=True)
    i = 0
    while rest != 0 and reihenfolge:
        k = reihenfolge[i % len(reihenfolge)]
        schritt = 1 if rest > 0 else -1
        basis[k] += schritt
        rest -= schritt
        i += 1
    return {k: v / 100 for k, v in basis.items()}


def verbrauch_zeitraum(messwerte: list, von: str, bis: str) -> dict:
    """messwerte: [(ts, wert)] aufsteigend. von/bis: 'YYYY-MM-DD' oder ''."""
    if not messwerte:
        return {"verbrauch": None, "start": None, "ende": None, "hinweise": ["keine Messwerte"]}
    hinweise = []
    bis_ts = f"{bis}T23:59:59" if bis else messwerte[-1][0]
    ende = None
    for ts, w in messwerte:
        if ts <= bis_ts:
            ende = (ts, w)
    if ende is None:
        return {"verbrauch": None, "start": None, "ende": None, "hinweise": ["kein Messwert bis zum Zeitraumende"]}
    start = None
    if von:
        von_ts = f"{von}T00:00:00"
        for ts, w in messwerte:
            if ts <= von_ts:
                start = (ts, w)
    if start is None:
        start = messwerte[0]
        hinweise.append(f"Startwert = erster Messwert ({start[0][:10]})")
    verbrauch = ende[1] - start[1]
    if verbrauch < 0:
        hinweise.append("Zaehlerstand gesunken (Zaehler zurueckgesetzt?) - bitte pruefen")
        verbrauch = 0.0
    if ende[0] == start[0]:
        hinweise.append("nur ein Messwert vorhanden")
    return {"verbrauch": verbrauch, "start": start, "ende": ende, "hinweise": hinweise}


def berechne(wohnungen: list, plaetze: list, gesamtkosten: float, verbrauchsanteil: int) -> dict:
    """Reine Rechenfunktion (ohne Datenbank).

    wohnungen: [{'id','bezeichnung','flaeche_qm'}]
    plaetze:   [{'id','typ','wohnung_id','raum','bezeichnung','heizkreis','hkv_typ','hoehe_cm',
                 'laenge_cm','kc_manuell','geraet_id','verbrauch'}]  (verbrauch = None wenn unbekannt)
    """
    if not 50 <= verbrauchsanteil <= 70:
        raise ValueError("Der Verbrauchsanteil muss laut HeizkostenV zwischen 50 und 70 Prozent liegen.")
    warnungen = []
    plaetze = [dict(p) for p in plaetze]

    hkv = [p for p in plaetze if p["typ"] == "HKV"]
    auto = bewertungsfaktoren(
        [
            {"id": p["id"], "typ": p["hkv_typ"], "hoehe_cm": p["hoehe_cm"], "laenge_cm": p["laenge_cm"]}
            for p in hkv
            if p.get("hkv_typ") and p.get("hoehe_cm") and p.get("laenge_cm")
        ]
    )
    ohne_faktor = 0
    for p in hkv:
        if p.get("kc_manuell"):
            p["kc"], p["kc_quelle"] = float(p["kc_manuell"]), "manuell"
        elif p["id"] in auto:
            p["kc"], p["kc_quelle"] = auto[p["id"]], "berechnet"
        else:
            p["kc"], p["kc_quelle"] = 1.0, "Standard"
            ohne_faktor += 1
        p["einheiten"] = (p.get("verbrauch") or 0.0) * p["kc"]
    if ohne_faktor:
        warnungen.append(
            f"{ohne_faktor} Heizkostenverteiler ohne Heizkoerper-Daten (Typ, Hoehe, Laenge): Bewertungsfaktor 1,0 angenommen."
        )
    ohne_messwert = [p for p in plaetze if p.get("verbrauch") is None]
    if ohne_messwert:
        warnungen.append(f"{len(ohne_messwert)} Geraet(e) ohne Messwerte im Zeitraum (zaehlen als 0).")

    wohnung_ids = [w["id"] for w in wohnungen]
    einheiten_kreis: dict = {}
    wmz_kwh: dict = {}
    wmz_direkt: dict = {}
    for p in plaetze:
        kreis = (p.get("heizkreis") or "1").strip() or "1"
        p["heizkreis"] = kreis
        if p["typ"] == "HKV":
            wid = p.get("wohnung_id")
            einheiten_kreis.setdefault(kreis, {})
            if wid:
                einheiten_kreis[kreis][wid] = einheiten_kreis[kreis].get(wid, 0.0) + p["einheiten"]
        else:
            wmz_kwh[kreis] = wmz_kwh.get(kreis, 0.0) + (p.get("verbrauch") or 0.0)
            if p.get("wohnung_id") and kreis not in wmz_direkt:
                wmz_direkt[kreis] = p["wohnung_id"]
    kreise = sorted(set(einheiten_kreis) | set(wmz_kwh) | set(wmz_direkt))

    verbrauchstopf = round(gesamtkosten * verbrauchsanteil / 100, 2)
    grundtopf = round(gesamtkosten - verbrauchstopf, 2)

    # 1) Verbrauchskosten auf Heizkreise
    kwh_gesamt = sum(wmz_kwh.values())
    kreis_kosten: dict = {}
    if kwh_gesamt > 0:
        for k in kreise:
            kreis_kosten[k] = verbrauchstopf * wmz_kwh.get(k, 0.0) / kwh_gesamt
    else:
        units_je_kreis = {k: sum(einheiten_kreis.get(k, {}).values()) for k in kreise}
        total_units = sum(units_je_kreis.values())
        if wmz_kwh or any(p["typ"] == "WMZ" for p in plaetze):
            warnungen.append(
                "Keine Waermemengenzaehler-Daten: Verbrauchskosten werden nur nach Heizkostenverteiler-Einheiten verteilt."
            )
        for k in kreise:
            kreis_kosten[k] = verbrauchstopf * units_je_kreis[k] / total_units if total_units > 0 else 0.0

    # 2) je Heizkreis auf Wohnungen
    verbrauch_wohnung = {wid: 0.0 for wid in wohnung_ids}
    kreis_info = []
    nicht_zugeordnet = 0.0
    for k in kreise:
        kosten = kreis_kosten.get(k, 0.0)
        units = einheiten_kreis.get(k, {})
        summe_units = sum(units.values())
        if summe_units > 0:
            for wid, u in units.items():
                if wid in verbrauch_wohnung:
                    verbrauch_wohnung[wid] += kosten * u / summe_units
                else:
                    nicht_zugeordnet += kosten * u / summe_units
        elif k in wmz_direkt and wmz_direkt[k] in verbrauch_wohnung:
            verbrauch_wohnung[wmz_direkt[k]] += kosten
        elif kosten > 0:
            nicht_zugeordnet += kosten
            warnungen.append(f"Heizkreis {k}: Kosten ohne zugeordnete Wohnung/Verteiler ({kosten:.2f} EUR).")
        kreis_info.append({"kreis": k, "kwh": wmz_kwh.get(k, 0.0), "kosten": round(kosten, 2)})

    # 3) Grundkosten nach Flaeche
    flaeche_gesamt = sum((w.get("flaeche_qm") or 0.0) for w in wohnungen)
    grund_wohnung = {wid: 0.0 for wid in wohnung_ids}
    if flaeche_gesamt > 0:
        for w in wohnungen:
            grund_wohnung[w["id"]] = grundtopf * (w.get("flaeche_qm") or 0.0) / flaeche_gesamt
    elif grundtopf > 0:
        warnungen.append("Wohnflaechen fehlen: Grundkosten koennen nicht verteilt werden.")

    verbrauch_gerundet = runden_summe(
        verbrauch_wohnung, sum(verbrauch_wohnung.values())
    )
    grund_gerundet = runden_summe(grund_wohnung, sum(grund_wohnung.values()))

    zeilen = []
    for w in wohnungen:
        wid = w["id"]
        mine = [p for p in plaetze if p.get("wohnung_id") == wid]
        vk = verbrauch_gerundet.get(wid, 0.0)
        gk = grund_gerundet.get(wid, 0.0)
        zeilen.append(
            {
                "id": wid,
                "bezeichnung": w.get("bezeichnung", ""),
                "flaeche_qm": w.get("flaeche_qm") or 0.0,
                "einheiten": round(sum(p.get("einheiten", 0.0) for p in mine if p["typ"] == "HKV"), 2),
                "kwh": round(sum(p.get("verbrauch") or 0.0 for p in mine if p["typ"] == "WMZ"), 2),
                "anteil_verbrauch_prozent": round(100 * vk / verbrauchstopf, 2) if verbrauchstopf else 0.0,
                "anteil_flaeche_prozent": round(100 * (w.get("flaeche_qm") or 0.0) / flaeche_gesamt, 2)
                if flaeche_gesamt
                else 0.0,
                "kosten_verbrauch": vk,
                "kosten_grund": gk,
                "kosten_gesamt": round(vk + gk, 2),
                "geraete": mine,
            }
        )
    return {
        "gesamtkosten": gesamtkosten,
        "verbrauchsanteil": verbrauchsanteil,
        "verbrauchstopf": verbrauchstopf,
        "grundtopf": grundtopf,
        "kreise": kreis_info,
        "wohnungen": zeilen,
        "nicht_zugeordnet": round(nicht_zugeordnet, 2),
        "warnungen": warnungen,
    }


def lade_und_berechne(con, gesamtkosten=None, verbrauchsanteil=None, von=None, bis=None) -> dict:
    """Daten aus der Datenbank holen und berechnen."""
    if gesamtkosten is None:
        raw = db.get_setting(con, "gesamtkosten", "").replace(",", ".").strip()
        gesamtkosten = float(raw) if raw else 0.0
    if verbrauchsanteil is None:
        verbrauchsanteil = int(db.get_setting(con, "verbrauchsanteil", "50") or 50)
    von = db.get_setting(con, "abrechnung_von", "") if von is None else von
    bis = db.get_setting(con, "abrechnung_bis", "") if bis is None else bis

    wohnungen = [dict(r) for r in con.execute("SELECT * FROM wohnung ORDER BY sort, id")]
    plaetze = [dict(r) for r in con.execute("SELECT * FROM platz ORDER BY id")]
    hinweise_je_platz = {}
    for p in plaetze:
        if not p["geraet_id"]:
            p["verbrauch"] = None
            continue
        rows = con.execute(
            "SELECT ts, wert FROM messung WHERE geraet_id = ? ORDER BY ts", (p["geraet_id"],)
        ).fetchall()
        res = verbrauch_zeitraum([(r["ts"], r["wert"]) for r in rows], von, bis)
        p["verbrauch"] = res["verbrauch"]
        p["start"], p["ende"] = res["start"], res["ende"]
        hinweise_je_platz[p["id"]] = res["hinweise"]
    ergebnis = berechne(wohnungen, plaetze, gesamtkosten, verbrauchsanteil)
    ergebnis["von"], ergebnis["bis"] = von, bis
    ergebnis["hinweise_je_platz"] = hinweise_je_platz
    return ergebnis
