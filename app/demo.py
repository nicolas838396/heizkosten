"""Demo-Daten: zeigt, wie die Seite mit echten Messwerten aussieht.

Wird ueber Einstellungen -> Demo-Ansicht ein- und ausgeschaltet. Die Demo nutzt eine
eigene Datenbank (demo.db); die echten Daten bleiben unangetastet."""

from __future__ import annotations

import datetime as dt
import random

# (Wohnung, Raum, Typ, Hoehe cm, Laenge cm, Heizkreis)
HEIZKOERPER = [
    ("EG", "Wohnzimmer", "22", 60, 120, "1"),
    ("EG", "Wohnzimmer", "22", 60, 80, "1"),
    ("EG", "Kueche", "21", 60, 100, "1"),
    ("EG", "Bad", "11", 90, 50, "1"),
    ("EG", "Schlafzimmer", "21", 60, 100, "1"),
    ("1OG", "Wohnzimmer", "22", 60, 140, "1"),
    ("1OG", "Kueche", "21", 60, 80, "1"),
    ("1OG", "Bad", "11", 90, 50, "1"),
    ("1OG", "Schlafzimmer", "21", 60, 100, "1"),
    ("1OG", "Kinderzimmer", "21", 60, 80, "1"),
    ("DG", "Wohnzimmer", "21", 60, 120, "1"),
    ("DG", "Bad", "10", 90, 50, "1"),
    ("DG", "Schlafzimmer", "21", 60, 80, "1"),
]

MONATS_GEWICHT = {1: 1.0, 2: 0.9, 3: 0.7, 4: 0.4, 5: 0.15, 6: 0.05, 7: 0.03, 8: 0.03, 9: 0.1, 10: 0.35, 11: 0.7, 12: 0.95}


def _zeitpunkte():
    punkte = []
    jahr, monat = 2025, 10
    while (jahr, monat) <= (2026, 9):
        punkte.append(dt.datetime(jahr, monat, 1, 0, 0, 0))
        monat += 1
        if monat == 13:
            jahr, monat = jahr + 1, 1
    punkte.append(dt.datetime(2026, 9, 30, 23, 0, 0))
    return punkte


def fill(con):
    rnd = random.Random(42)
    jetzt = dt.datetime.now().replace(microsecond=0).isoformat()
    einst = {
        "gesamtkosten": "4850,00",
        "verbrauchsanteil": "60",
        "abrechnung_von": "2025-10-01",
        "abrechnung_bis": "2026-09-30",
    }
    for k, v in einst.items():
        con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, v))
    wohnungen = [
        ("EG", "Erdgeschoss", 62.5, "Mieter", 1),
        ("1OG", "1. Obergeschoss", 71.0, "Mieter", 2),
        ("DG", "Dachgeschoss", 54.0, "Eigennutzung", 3),
        ("KELLER", "Kellergeschoss", 38.0, "Mieter", 4),
    ]
    for wid, bez, qm, nutzung, sort in wohnungen:
        con.execute(
            "INSERT OR REPLACE INTO wohnung (id, bezeichnung, flaeche_qm, nutzung, sort) VALUES (?, ?, ?, ?, ?)",
            (wid, bez, qm, nutzung, sort),
        )

    zeitpunkte = _zeitpunkte()
    geraet_nr = 0

    def verlauf(gesamt):
        werte, summe = [], 0.0
        gewichte = [MONATS_GEWICHT[z.month] * rnd.uniform(0.9, 1.1) for z in zeitpunkte]
        total_w = sum(gewichte)
        for g in gewichte:
            summe += gesamt * g / total_w
            werte.append(round(summe, 1))
        return werte

    def messung_einfuegen(gid, werte, einheit):
        for z, w in zip(zeitpunkte, werte):
            con.execute(
                "INSERT OR IGNORE INTO messung (geraet_id, ts, wert, einheit, quelle) VALUES (?, ?, ?, ?, 'funk')",
                (gid, z.isoformat(), w, einheit),
            )
        con.execute(
            "INSERT OR IGNORE INTO gesehen (geraet_id, hersteller, erste, zuletzt, anzahl, rssi) VALUES (?, 'ENG', ?, ?, 400, -78)",
            (gid, zeitpunkte[0].isoformat(), jetzt),
        )

    for wohnung, raum, typ, hoehe, laenge, kreis in HEIZKOERPER:
        geraet_nr += 1
        gid = f"9900{geraet_nr:04d}"
        con.execute(
            "INSERT INTO platz (typ, wohnung_id, raum, bezeichnung, heizkreis, hkv_typ, hoehe_cm, laenge_cm, geraet_id, aes_key, erstellt) "
            "VALUES ('HKV', ?, ?, ?, ?, ?, ?, ?, ?, '00112233445566778899AABBCCDDEEFF', ?)",
            (wohnung, raum, f"Heizkoerper {raum}", kreis, typ, hoehe, laenge, gid, jetzt),
        )
        messung_einfuegen(gid, verlauf(rnd.uniform(180, 520) * (laenge / 100)), "Einheiten")

    con.execute(
        "INSERT INTO platz (typ, wohnung_id, raum, bezeichnung, heizkreis, geraet_id, aes_key, erstellt) "
        "VALUES ('WMZ', NULL, 'Heizungsraum', 'Waermemengenzaehler Heizkreis 1', '1', '99100001', '00112233445566778899AABBCCDDEEFF', ?)",
        (jetzt,),
    )
    messung_einfuegen("99100001", verlauf(38500.0), "kWh")
    con.execute(
        "INSERT INTO platz (typ, wohnung_id, raum, bezeichnung, heizkreis, geraet_id, aes_key, erstellt) "
        "VALUES ('WMZ', 'KELLER', 'Heizungsraum', 'Waermemengenzaehler Heizkreis 2 (Fussbodenheizung)', '2', '99100002', '00112233445566778899AABBCCDDEEFF', ?)",
        (jetzt,),
    )
    messung_einfuegen("99100002", verlauf(5200.0), "kWh")
    # ein noch nicht zugeordnetes, gerade empfangenes Geraet
    con.execute(
        "INSERT OR IGNORE INTO gesehen (geraet_id, hersteller, erste, zuletzt, anzahl, rssi) VALUES ('99990001', 'ENG', ?, ?, 3, -91)",
        (jetzt, jetzt),
    )
    # ein geplanter Platz ohne Geraet
    con.execute(
        "INSERT INTO platz (typ, wohnung_id, raum, bezeichnung, heizkreis, hkv_typ, hoehe_cm, laenge_cm, erstellt) "
        "VALUES ('HKV', 'EG', 'Flur', 'Heizkoerper Flur (geplant)', '1', '11', 60, 60, ?)",
        (jetzt,),
    )
