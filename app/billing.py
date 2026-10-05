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

Warmwasser und Kaltwasser
-------------------------
* Heizenergie-Gesamtkosten werden nach Waermemenge in Warmwasser und Heizung geteilt:
  Warmwasser-kWh / (Warmwasser-kWh + Summe der Heizkreis-kWh). Die Warmwasser-kWh kommen vom
  Funk-Waermemengenzaehler (Heizkreis "WW"), sonst vom abgelesenen Waermemengenzaehler, sonst
  aus der Formel 2,5 kWh x m3 x (t - 10 C) nach 9 HeizkostenV.
* Warmwasser-Energiekosten: 50-70 % nach Warmwasser-m3 der Wohnung, Rest nach Wohnflaeche.
* Wasser/Abwasser-Kosten: ein Preis je m3 aus (Kaltwasser-m3 + Warmwasser-m3 aller Wohnungen).
  Das Kaltwasser steht als eigener Block, das Wasser fuer das Warmwasser gehoert zum Warmwasser.

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


ZAEHLER_ENERGIE_KWH = {"kWh": 1.0, "MWh": 1000.0, "GJ": 277.7778}


def _istww(p: dict) -> bool:
    return p["typ"] == "WMZ" and (p.get("heizkreis") or "").strip().upper() == "WW"


def berechne_alles(wohnungen: list, plaetze: list, zaehler: list, einst: dict) -> dict:
    """Heizung + Warmwasser + Kaltwasser.

    zaehler: [{'id','art','wohnung_id','bezeichnung','einheit','verbrauch', ...}]
    einst:   gesamtkosten (Heizenergie inkl. Warmwasser), wasserkosten, verbrauchsanteil,
             ww_verbrauchsanteil, ww_temperatur, ww_pauschal (Prozent oder None)
    """
    gesamt = float(einst.get("gesamtkosten") or 0.0)
    wasserkosten = float(einst.get("wasserkosten") or 0.0)
    ww_va = int(einst.get("ww_verbrauchsanteil") or 70)
    temp = float(einst.get("ww_temperatur") or 60.0)
    pauschal = einst.get("ww_pauschal")
    if not 50 <= ww_va <= 70:
        raise ValueError("Der Verbrauchsanteil fuer Warmwasser muss zwischen 50 und 70 Prozent liegen.")
    warnungen: list = []
    wids = [w["id"] for w in wohnungen]

    ww_plaetze = [p for p in plaetze if _istww(p)]
    heiz_plaetze = [p for p in plaetze if not _istww(p)]

    # --- Wasser-m3 je Wohnung
    m3 = {"WARM": {w: 0.0 for w in wids}, "KALT": {w: 0.0 for w in wids}}
    ohne_wert = ohne_wohnung = 0
    for z in zaehler:
        if z["art"] not in m3:
            continue
        if z.get("verbrauch") is None:
            ohne_wert += 1
            continue
        if z.get("wohnung_id") in m3[z["art"]]:
            m3[z["art"]][z["wohnung_id"]] += z["verbrauch"]
        else:
            ohne_wohnung += 1
    if ohne_wert:
        warnungen.append(f"{ohne_wert} Wasserzaehler ohne Ablesung im Zeitraum (zaehlen als 0).")
    if ohne_wohnung:
        warnungen.append(f"{ohne_wohnung} Wasserzaehler ohne Wohnung werden nicht verteilt.")
    m3_warm_ges = sum(m3["WARM"].values())
    m3_kalt_ges = sum(m3["KALT"].values())

    # --- Waermemenge Warmwasser
    kwh_funk = [p["verbrauch"] for p in ww_plaetze if p.get("verbrauch") is not None]
    kwh_hand = [
        z["verbrauch"] * ZAEHLER_ENERGIE_KWH.get(z.get("einheit"), 1.0)
        for z in zaehler
        if z["art"] == "WW_WAERME" and z.get("verbrauch") is not None
    ]
    if kwh_funk:
        ww_kwh, ww_quelle = sum(kwh_funk), "Funk-Waermemengenzaehler"
    elif kwh_hand:
        ww_kwh, ww_quelle = sum(kwh_hand), "abgelesener Waermemengenzaehler"
    elif m3_warm_ges > 0:
        ww_kwh = 2.5 * m3_warm_ges * (temp - 10.0)
        ww_quelle = f"Berechnung nach 9 HeizkostenV (2,5 kWh x m3 x ({temp:g} - 10 C))"
        warnungen.append(
            "Kein Waermemengenzaehler fuer Warmwasser: Waermemenge aus Warmwasser-m3 berechnet (Formel nach HeizkostenV)."
        )
    else:
        ww_kwh, ww_quelle = 0.0, "keine Daten"

    kwh_heiz = sum((p.get("verbrauch") or 0.0) for p in heiz_plaetze if p["typ"] == "WMZ")
    ww_energie = 0.0
    if ww_kwh > 0 and kwh_heiz > 0:
        ww_energie = gesamt * ww_kwh / (ww_kwh + kwh_heiz)
    elif ww_kwh > 0 and pauschal:
        ww_energie = gesamt * float(pauschal) / 100.0
        warnungen.append(f"Warmwasseranteil pauschal mit {float(pauschal):g} % angesetzt (keine Heizkreis-Waermemengen).")
    elif ww_kwh > 0 and gesamt > 0:
        warnungen.append(
            "Ohne Waermemengen der Heizkreise ist der Warmwasseranteil nicht bestimmbar. "
            "Alle Heizenergiekosten laufen derzeit in die Heizung; unter 'Weitere Einstellungen' kann ein Pauschalanteil gesetzt werden."
        )
    ww_energie = round(ww_energie, 2)

    heiz = berechne(wohnungen, heiz_plaetze, round(gesamt - ww_energie, 2), int(einst.get("verbrauchsanteil") or 50))
    heiz["warnungen"] = list(heiz["warnungen"]) + warnungen
    warnungen = heiz["warnungen"]

    # --- Warmwasser-Energiekosten verteilen
    flaeche_ges = sum((w.get("flaeche_qm") or 0.0) for w in wohnungen)
    topf_v = round(ww_energie * ww_va / 100, 2)
    topf_g = round(ww_energie - topf_v, 2)
    v_teile = {w: 0.0 for w in wids}
    g_teile = {w: 0.0 for w in wids}
    if m3_warm_ges > 0:
        for w in wids:
            v_teile[w] = topf_v * m3["WARM"][w] / m3_warm_ges
    elif flaeche_ges > 0:
        for w in wohnungen:
            v_teile[w["id"]] = topf_v * (w.get("flaeche_qm") or 0.0) / flaeche_ges
        if topf_v > 0:
            warnungen.append("Keine Warmwasser-m3: Verbrauchsanteil des Warmwassers wird nach Wohnflaeche verteilt.")
    if flaeche_ges > 0:
        for w in wohnungen:
            g_teile[w["id"]] = topf_g * (w.get("flaeche_qm") or 0.0) / flaeche_ges
    elif topf_g > 0:
        warnungen.append("Wohnflaechen fehlen: Grundkosten Warmwasser koennen nicht verteilt werden.")
    v_r = runden_summe(v_teile, sum(v_teile.values()))
    g_r = runden_summe(g_teile, sum(g_teile.values()))

    # --- Wasser/Abwasser
    total_m3 = m3_warm_ges + m3_kalt_ges
    preis = wasserkosten / total_m3 if wasserkosten > 0 and total_m3 > 0 else 0.0
    if wasserkosten > 0 and total_m3 <= 0:
        warnungen.append("Wasserkosten eingegeben, aber keine Wasser-m3 abgelesen: Kosten koennen nicht verteilt werden.")
    teile = {}
    for w in wids:
        teile[("K", w)] = m3["KALT"][w] * preis
        teile[("W", w)] = m3["WARM"][w] * preis
    w_r = runden_summe(teile, sum(teile.values()))

    for z in heiz["wohnungen"]:
        wid = z["id"]
        z["heizung_gesamt"] = z["kosten_gesamt"]
        z["m3_warm"] = round(m3["WARM"][wid], 3)
        z["m3_kalt"] = round(m3["KALT"][wid], 3)
        z["ww_energie_verbrauch"] = v_r.get(wid, 0.0)
        z["ww_energie_grund"] = g_r.get(wid, 0.0)
        z["ww_wasser"] = w_r.get(("W", wid), 0.0)
        z["ww_gesamt"] = round(z["ww_energie_verbrauch"] + z["ww_energie_grund"] + z["ww_wasser"], 2)
        z["kalt_kosten"] = w_r.get(("K", wid), 0.0)
        z["summe_gesamt"] = round(z["heizung_gesamt"] + z["ww_gesamt"] + z["kalt_kosten"], 2)
        z["zaehler"] = [q for q in zaehler if q.get("wohnung_id") == wid and q["art"] in m3]

    heiz["energie_gesamt"] = gesamt
    heiz["wasser"] = {
        "wasserkosten": wasserkosten,
        "preis_m3": preis,
        "m3_warm": round(m3_warm_ges, 3),
        "m3_kalt": round(m3_kalt_ges, 3),
        "ww_kwh": round(ww_kwh, 1),
        "ww_quelle": ww_quelle,
        "ww_energie": ww_energie,
        "ww_verbrauchsanteil": ww_va,
        "ww_verbrauchstopf": topf_v,
        "ww_grundtopf": topf_g,
        "heiz_kwh": round(kwh_heiz, 1),
        "ww_zaehler": [z for z in zaehler if z["art"] == "WW_WAERME"],
    }
    heiz["summe_haus"] = round(sum(z["summe_gesamt"] for z in heiz["wohnungen"]), 2)
    return heiz


def _zahl(raw, default=None):
    raw = (raw or "").replace(",", ".").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def lade_und_berechne(con, gesamtkosten=None, verbrauchsanteil=None, von=None, bis=None) -> dict:
    """Daten aus der Datenbank holen und berechnen."""
    if gesamtkosten is None:
        gesamtkosten = _zahl(db.get_setting(con, "gesamtkosten", ""), 0.0)
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

    zaehler = [dict(r) for r in con.execute("SELECT * FROM zaehler ORDER BY wohnung_id IS NULL, wohnung_id, art, id")]
    for z in zaehler:
        rows = con.execute(
            "SELECT datum, wert FROM ablesung WHERE zaehler_id = ? ORDER BY datum, id", (z["id"],)
        ).fetchall()
        res = verbrauch_zeitraum([(f"{r['datum']}T00:00:00", r["wert"]) for r in rows], von, bis)
        z["verbrauch"] = res["verbrauch"] if rows else None
        z["start"], z["ende"], z["hinweise"] = res["start"], res["ende"], res["hinweise"]

    einst = {
        "gesamtkosten": gesamtkosten,
        "wasserkosten": _zahl(db.get_setting(con, "wasserkosten", ""), 0.0),
        "verbrauchsanteil": verbrauchsanteil,
        "ww_verbrauchsanteil": int(_zahl(db.get_setting(con, "ww_verbrauchsanteil", "70"), 70)),
        "ww_temperatur": _zahl(db.get_setting(con, "ww_temperatur", "60"), 60.0),
        "ww_pauschal": _zahl(db.get_setting(con, "ww_pauschal_prozent", ""), None),
    }
    ergebnis = berechne_alles(wohnungen, plaetze, zaehler, einst)
    ergebnis["von"], ergebnis["bis"] = von, bis
    ergebnis["hinweise_je_platz"] = hinweise_je_platz
    return ergebnis
