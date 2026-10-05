import os
import tempfile
import unittest

from app import billing, report, schnell, telegrams, values
from app.kc import bewertungsfaktoren


class TelegramTests(unittest.TestCase):
    def test_kopf_lesen(self):
        t = telegrams.parse_telegram_hex("1844C7154455223368077A55000000_041389E20100")
        self.assertEqual(t["geraet_id"], "33225544")
        self.assertEqual(t["hersteller"], "ENG")
        self.assertEqual(t["version"], 0x68)
        self.assertEqual(t["medium"], 7)

    def test_zu_kurz(self):
        self.assertIsNone(telegrams.parse_telegram_hex("1844"))
        self.assertIsNone(telegrams.parse_telegram_hex("ZZ" * 12))

    def test_log_inkrementell(self):
        with tempfile.TemporaryDirectory() as d:
            pfad = os.path.join(d, "w.log")
            with open(pfad, "w") as f:
                f.write("irgendwas\ntelegram=|1844C7154455223368077A55|+7\n")
                f.write("telegram=|1844C7156655223368077A55|-81")  # unvollstaendige letzte Zeile
            liste, off = telegrams.scan_new_lines(pfad, 0)
            self.assertEqual([t["geraet_id"] for t in liste], ["33225544"])
            self.assertEqual(liste[0]["rssi"], 7)
            with open(pfad, "a") as f:
                f.write("\n")
            liste2, off2 = telegrams.scan_new_lines(pfad, off)
            self.assertEqual([t["geraet_id"] for t in liste2], ["33225566"])
            self.assertEqual(liste2[0]["rssi"], -81)
            self.assertEqual(telegrams.scan_new_lines(pfad, off2)[0], [])


class ValueTests(unittest.TestCase):
    def test_hkv(self):
        self.assertEqual(values.extract_value("HKV", {"current_consumption_hca": "123"})[0], 123.0)

    def test_wmz_gj(self):
        wert, einheit, _ = values.extract_value("WMZ", {"total_energy_consumption_gj": 1.0})
        self.assertAlmostEqual(wert, 277.7778, places=3)
        self.assertEqual(einheit, "kWh")

    def test_unbekannt(self):
        self.assertEqual(values.extract_value("HKV", {"foo": 1}), (None, None, None))


class SchnellTests(unittest.TestCase):
    def test_parse(self):
        res = schnell.parse("EG: Wohnzimmer 2, Küche, Bad 1\n1. OG: Schlafzimmer\nohne doppelpunkt")
        self.assertEqual(res, [("EG", "Wohnzimmer", 2), ("EG", "Küche", 1), ("EG", "Bad", 1), ("1. OG", "Schlafzimmer", 1)])

    def test_wohnung_finden(self):
        w = [{"id": "EG", "bezeichnung": "Erdgeschoss"}, {"id": "1OG", "bezeichnung": "1. Obergeschoss"}]
        self.assertEqual(schnell.finde_wohnung("eg", w), "EG")
        self.assertEqual(schnell.finde_wohnung("1. OG", w), "1OG")
        self.assertEqual(schnell.finde_wohnung("Erdgeschoss", w), "EG")
        self.assertIsNone(schnell.finde_wohnung("Dach", w))


class KcTests(unittest.TestCase):
    def test_kleinster_ist_eins(self):
        f = bewertungsfaktoren(
            [
                {"id": "a", "typ": "21", "hoehe_cm": 60, "laenge_cm": 100},
                {"id": "b", "typ": "10", "hoehe_cm": 60, "laenge_cm": 60},
                {"id": "c", "typ": "33", "hoehe_cm": 90, "laenge_cm": 120},
            ]
        )
        self.assertEqual(f["b"], 1.0)
        self.assertAlmostEqual(f["a"], 3.2868, places=3)
        self.assertAlmostEqual(f["c"], 7.9061, places=3)


def hkv(pid, wid, verbrauch, kreis="1", kc=None):
    return {"id": pid, "typ": "HKV", "wohnung_id": wid, "raum": "R", "bezeichnung": "", "heizkreis": kreis,
            "hkv_typ": "", "hoehe_cm": None, "laenge_cm": None, "kc_manuell": kc, "geraet_id": f"G{pid}",
            "verbrauch": verbrauch}


def wmz(pid, wid, kwh, kreis):
    return {"id": pid, "typ": "WMZ", "wohnung_id": wid, "raum": "H", "bezeichnung": "", "heizkreis": kreis,
            "hkv_typ": "", "hoehe_cm": None, "laenge_cm": None, "kc_manuell": None, "geraet_id": f"W{pid}",
            "verbrauch": kwh}


class BillingTests(unittest.TestCase):
    def setUp(self):
        self.wohnungen = [
            {"id": "A", "bezeichnung": "A", "flaeche_qm": 50.0},
            {"id": "B", "bezeichnung": "B", "flaeche_qm": 50.0},
        ]

    def test_nur_hkv(self):
        plaetze = [hkv(1, "A", 300, kc=1.0), hkv(2, "B", 100, kc=1.0)]
        r = billing.berechne(self.wohnungen, plaetze, 1000.0, 50)
        a, b = r["wohnungen"]
        self.assertEqual(a["kosten_verbrauch"], 375.0)
        self.assertEqual(b["kosten_verbrauch"], 125.0)
        self.assertEqual(a["kosten_grund"], 250.0)
        self.assertEqual(b["kosten_grund"], 250.0)
        self.assertEqual(a["kosten_gesamt"] + b["kosten_gesamt"], 1000.0)

    def test_summe_exakt_bei_krummen_zahlen(self):
        w = [{"id": x, "bezeichnung": x, "flaeche_qm": f} for x, f in (("A", 33.3), ("B", 41.7), ("C", 27.1))]
        plaetze = [hkv(1, "A", 111, kc=1.1), hkv(2, "B", 222, kc=0.9), hkv(3, "C", 333, kc=1.3)]
        r = billing.berechne(w, plaetze, 4321.99, 60)
        summe = round(sum(z["kosten_gesamt"] for z in r["wohnungen"]), 2)
        self.assertEqual(summe, 4321.99)

    def test_heizkreise_mit_wmz(self):
        # Kreis 1: 3000 kWh (Wohnung A und B per HKV 3:1), Kreis 2: 1000 kWh direkt auf Wohnung K
        w = self.wohnungen + [{"id": "K", "bezeichnung": "K", "flaeche_qm": 0.0}]
        plaetze = [hkv(1, "A", 300, "1", 1.0), hkv(2, "B", 100, "1", 1.0), wmz(3, None, 3000, "1"), wmz(4, "K", 1000, "2")]
        r = billing.berechne(w, plaetze, 4000.0, 50)
        z = {x["id"]: x for x in r["wohnungen"]}
        # Verbrauchstopf 2000: Kreis1 1500 (A 1125, B 375), Kreis2 500 (K)
        self.assertEqual(z["A"]["kosten_verbrauch"], 1125.0)
        self.assertEqual(z["B"]["kosten_verbrauch"], 375.0)
        self.assertEqual(z["K"]["kosten_verbrauch"], 500.0)
        self.assertEqual(z["K"]["kosten_grund"], 0.0)
        self.assertEqual(round(sum(x["kosten_gesamt"] for x in r["wohnungen"]), 2), 4000.0)

    def test_verbrauchsanteil_grenzen(self):
        with self.assertRaises(ValueError):
            billing.berechne(self.wohnungen, [], 100.0, 40)
        with self.assertRaises(ValueError):
            billing.berechne(self.wohnungen, [], 100.0, 80)

    def test_zeitraum(self):
        werte = [("2025-10-01T00:00:00", 0.0), ("2026-01-01T00:00:00", 100.0), ("2026-09-30T23:00:00", 400.0)]
        r = billing.verbrauch_zeitraum(werte, "2025-10-01", "2026-09-30")
        self.assertEqual(r["verbrauch"], 400.0)
        r = billing.verbrauch_zeitraum(werte, "2026-01-01", "")
        self.assertEqual(r["verbrauch"], 300.0)
        r = billing.verbrauch_zeitraum(werte, "", "2025-12-31")
        self.assertEqual(r["verbrauch"], 0.0)
        self.assertIsNone(billing.verbrauch_zeitraum([], "", "")["verbrauch"])

    def test_pdf(self):
        plaetze = [hkv(1, "A", 300, kc=1.0), hkv(2, "B", 100, kc=1.0)]
        r = billing.berechne_alles(self.wohnungen, plaetze, [], EINST)
        data = report.wohnung_pdf(r, "A", "Testhaus", "Heizkostenabrechnung")
        self.assertTrue(data.startswith(b"%PDF-1.4"))
        self.assertTrue(data.rstrip().endswith(b"%%EOF"))
        with self.assertRaises(KeyError):
            report.wohnung_pdf(r, "X", "Testhaus", "T")

    # ---- Warmwasser / Kaltwasser
    def test_wasser_kostenbloecke(self):
        plaetze = [
            hkv(1, "A", 300, kc=1.0),
            hkv(2, "B", 100, kc=1.0),
            {"id": 8, "typ": "WMZ", "wohnung_id": None, "heizkreis": "1", "verbrauch": 8000.0},
            {"id": 9, "typ": "WMZ", "wohnung_id": None, "heizkreis": "WW", "verbrauch": 2000.0},
        ]
        zaehler = [
            {"id": 1, "art": "WARM", "wohnung_id": "A", "verbrauch": 30.0},
            {"id": 2, "art": "WARM", "wohnung_id": "A", "verbrauch": 10.0},
            {"id": 3, "art": "WARM", "wohnung_id": "B", "verbrauch": 40.0},
            {"id": 4, "art": "KALT", "wohnung_id": "A", "verbrauch": 60.0},
            {"id": 5, "art": "KALT", "wohnung_id": "B", "verbrauch": 60.0},
        ]
        einst = dict(EINST, gesamtkosten=1000.0, wasserkosten=1000.0)
        r = billing.berechne_alles(self.wohnungen, plaetze, zaehler, einst)
        wa = r["wasser"]
        # Warmwasser 2000 von 10000 kWh = 20 % von 1000 = 200
        self.assertEqual(wa["ww_energie"], 200.0)
        self.assertEqual(r["gesamtkosten"], 800.0)
        z = {x["id"]: x for x in r["wohnungen"]}
        # Wasserpreis 1000 / 200 m3 = 5 EUR; A: 40 m3 warm, 60 kalt; B: 40 warm, 60 kalt
        self.assertEqual(z["A"]["kalt_kosten"], 300.0)
        self.assertEqual(z["A"]["ww_wasser"], 200.0)
        self.assertEqual(z["B"]["ww_wasser"], 200.0)
        # Energie Warmwasser 200: Verbrauch 70 % = 140, je 70 nach m3 (40/40)
        self.assertEqual(z["A"]["ww_energie_verbrauch"], 70.0)
        # Summe aller Wohnungen = Heizenergie + Wasser (nur A und B haben Flaeche/Zaehler)
        self.assertAlmostEqual(r["summe_haus"], 1000.0 + 1000.0 - r["nicht_zugeordnet"] - 0.0, places=2)

    def test_wasser_formel_ohne_waermezaehler(self):
        zaehler = [{"id": 1, "art": "WARM", "wohnung_id": "A", "verbrauch": 100.0}]
        einst = dict(EINST, gesamtkosten=1000.0, ww_pauschal=25.0)
        plaetze = [hkv(1, "A", 100, kc=1.0)]
        r = billing.berechne_alles(self.wohnungen, plaetze, zaehler, einst)
        # 2,5 kWh x 100 m3 x 50 K = 12500 kWh; ohne Heizkreis-kWh gilt der Pauschalanteil 25 %
        self.assertEqual(r["wasser"]["ww_kwh"], 12500.0)
        self.assertEqual(r["wasser"]["ww_energie"], 250.0)
        self.assertTrue(any("Formel" in w for w in r["warnungen"]))

    def test_wasser_handzaehler_mwh(self):
        zaehler = [{"id": 1, "art": "WW_WAERME", "wohnung_id": None, "einheit": "MWh", "verbrauch": 2.0}]
        plaetze = [{"id": 8, "typ": "WMZ", "wohnung_id": None, "heizkreis": "1", "verbrauch": 8000.0}]
        r = billing.berechne_alles(self.wohnungen, plaetze, zaehler, dict(EINST, gesamtkosten=1000.0))
        self.assertEqual(r["wasser"]["ww_kwh"], 2000.0)
        self.assertEqual(r["wasser"]["ww_energie"], 200.0)

    def test_wasser_ohne_daten_aendert_heizung_nicht(self):
        plaetze = [hkv(1, "A", 300, kc=1.0), hkv(2, "B", 100, kc=1.0)]
        r1 = billing.berechne(self.wohnungen, plaetze, 1000.0, 50)
        r2 = billing.berechne_alles(self.wohnungen, plaetze, [], dict(EINST, gesamtkosten=1000.0))
        self.assertEqual(
            [x["kosten_gesamt"] for x in r1["wohnungen"]], [x["heizung_gesamt"] for x in r2["wohnungen"]]
        )
        self.assertEqual(r2["wasser"]["ww_energie"], 0.0)

    def test_ww_verbrauchsanteil_grenzen(self):
        with self.assertRaises(ValueError):
            billing.berechne_alles(self.wohnungen, [], [], dict(EINST, ww_verbrauchsanteil=30))


EINST = {
    "gesamtkosten": 1000.0,
    "wasserkosten": 0.0,
    "verbrauchsanteil": 50,
    "ww_verbrauchsanteil": 70,
    "ww_temperatur": 60.0,
    "ww_pauschal": None,
}


if __name__ == "__main__":
    unittest.main()
