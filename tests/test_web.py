import os
import tempfile
import unittest

import tests  # noqa: F401  (setzt HEIZKOSTEN_DATA)

_TMP = os.environ["HEIZKOSTEN_DATA"]

from app import collector, db  # noqa: E402
from app.web import create_app  # noqa: E402


class WebTests(unittest.TestCase):
    def setUp(self):
        db.set_demo(False)
        for name in ("heizkosten.db", "demo.db", "passwort.txt", "benutzer.txt"):
            p = os.path.join(_TMP, name)
            if os.path.exists(p):
                os.remove(p)
        self.app = create_app()
        self.c = self.app.test_client()

    def test_leere_installation(self):
        for url in ("/", "/plaetze", "/wohnungen", "/empfang", "/abrechnung", "/einstellungen", "/platz/neu"):
            r = self.c.get(url)
            self.assertEqual(r.status_code, 200, url)
        self.assertIn("Erdgeschoss", self.c.get("/wohnungen").get_data(as_text=True))

    def test_schnellerfassung_und_zuordnung(self):
        r = self.c.post("/plaetze/schnell", data={"liste": "EG: Wohnzimmer 2, Küche\nDachstudio: Bad"}, follow_redirects=True)
        text = r.get_data(as_text=True)
        self.assertIn("4 Plätze angelegt", text)
        con = db.connect()
        self.assertEqual(con.execute("SELECT COUNT(*) FROM platz WHERE typ='HKV'").fetchone()[0], 4)
        self.assertIsNotNone(con.execute("SELECT 1 FROM wohnung WHERE bezeichnung='Dachstudio'").fetchone())
        pid = con.execute("SELECT id FROM platz WHERE raum='Küche'").fetchone()[0]
        collector.note_seen(con, "12345678", "ENG", 1, 8, -80)
        con.commit()
        con.close()
        r = self.c.post("/empfang/zuordnen", data={"geraet_id": "12345678", "platz_id": str(pid)}, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        con = db.connect()
        self.assertEqual(con.execute("SELECT geraet_id FROM platz WHERE id=?", (pid,)).fetchone()[0], "12345678")
        self.assertEqual(db.get_setting(con, "config_dirty"), "1")
        con.close()

    def test_doppelte_geraete_id(self):
        d = {"typ": "HKV", "raum": "A", "geraet_id": "1234", "heizkreis": "1"}
        self.assertEqual(self.c.post("/platz/neu", data=d).status_code, 302)
        self.assertEqual(self.c.post("/platz/neu", data=d).status_code, 400)
        con = db.connect()
        self.assertEqual(con.execute("SELECT geraet_id FROM platz WHERE raum='A'").fetchone()[0], "00001234")
        con.close()

    def test_platz_bearbeiten_und_loeschen(self):
        self.c.post("/platz/neu", data={"typ": "HKV", "raum": "Flur", "wohnung_id": "EG", "hkv_typ": "21",
                                       "hoehe_cm": "60", "laenge_cm": "100", "aes_key": "00 11-22 zz"})
        con = db.connect()
        pid = con.execute("SELECT id, aes_key FROM platz WHERE raum='Flur'").fetchone()
        self.assertEqual(pid["aes_key"], "001122")
        con.close()
        self.assertEqual(self.c.get(f"/platz/{pid['id']}").status_code, 200)
        self.assertEqual(self.c.get(f"/platz/{pid['id']}/messwerte").status_code, 200)
        self.assertEqual(self.c.post(f"/platz/{pid['id']}/loeschen").status_code, 302)
        self.assertEqual(self.c.get(f"/platz/{pid['id']}").status_code, 404)

    def test_demo_abrechnung_und_pdf(self):
        r = self.c.post("/einstellungen", data={"aktion": "demo", "an": "1"})
        self.assertEqual(r.status_code, 302)
        page = self.c.get("/abrechnung")
        self.assertEqual(page.status_code, 200)
        text = page.get_data(as_text=True)
        self.assertIn("Erdgeschoss", text)
        self.assertIn("PDF", text)
        for url in ("/", "/plaetze", "/empfang", "/einstellungen"):
            self.assertEqual(self.c.get(url).status_code, 200, url)
        pdf = self.c.get("/pdf/EG.pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.mimetype, "application/pdf")
        self.assertTrue(pdf.data.startswith(b"%PDF"))
        with open(os.path.join(_TMP, "demo-EG.pdf"), "wb") as f:
            f.write(pdf.data)
        self.assertEqual(self.c.get("/pdf/GIBTESNICHT.pdf").status_code, 404)
        con = db.connect()
        from app import billing
        r = billing.lade_und_berechne(con)
        self.assertEqual(round(sum(w["kosten_gesamt"] for w in r["wohnungen"]), 2), 4850.0)
        con.close()
        self.c.post("/einstellungen", data={"aktion": "demo", "an": "0"})
        self.assertFalse(db.demo_active())

    def test_manueller_messwert(self):
        self.c.post("/platz/neu", data={"typ": "WMZ", "raum": "Heizungsraum", "geraet_id": "99"})
        con = db.connect()
        pid = con.execute("SELECT id FROM platz WHERE raum='Heizungsraum' AND geraet_id IS NOT NULL").fetchone()[0]
        con.close()
        r = self.c.post(f"/platz/{pid}/messwerte", data={"datum": "2026-01-01", "wert": "1234,5"})
        self.assertEqual(r.status_code, 302)
        con = db.connect()
        row = con.execute("SELECT wert, einheit, quelle FROM messung").fetchone()
        self.assertEqual((row["wert"], row["einheit"], row["quelle"]), (1234.5, "kWh", "manuell"))
        con.close()

    def test_collector_meterfile(self):
        con = db.connect()
        con.execute("INSERT INTO platz (typ, raum, geraet_id) VALUES ('HKV', 'X', '00ABCDEF')")
        con.commit()
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "g00ABCDEF"), "w") as f:
                f.write('{"id":"00abcdef","current_consumption_hca":42,"timestamp":"2026-10-05T14:28:03Z"}\n')
            self.assertEqual(collector.scan_meterfiles(con, d), 1)
            self.assertEqual(collector.scan_meterfiles(con, d), 0)  # keine Doppelten
        self.assertEqual(con.execute("SELECT wert FROM messung WHERE geraet_id='00ABCDEF'").fetchone()[0], 42.0)
        con.commit()
        con.close()

    def test_passwortschutz(self):
        with open(os.path.join(_TMP, "passwort.txt"), "w") as f:
            f.write("geheim123")
        self.assertEqual(self.c.get("/").status_code, 401)
        self.assertEqual(self.c.get("/health").status_code, 200)
        import base64
        ok = {"Authorization": "Basic " + base64.b64encode(b"x:geheim123").decode()}
        bad = {"Authorization": "Basic " + base64.b64encode(b"x:falsch").decode()}
        self.assertEqual(self.c.get("/", headers=ok).status_code, 200)
        self.assertEqual(self.c.get("/", headers=bad).status_code, 401)

    def test_benutzername(self):
        import base64
        with open(os.path.join(_TMP, "passwort.txt"), "w") as f:
            f.write("geheim123")
        with open(os.path.join(_TMP, "benutzer.txt"), "w") as f:
            f.write("nico")
        def h(cred):
            return {"Authorization": "Basic " + base64.b64encode(cred).decode()}
        self.assertEqual(self.c.get("/", headers=h(b"nico:geheim123")).status_code, 200)
        self.assertEqual(self.c.get("/", headers=h(b"anderer:geheim123")).status_code, 401)
        self.assertEqual(self.c.get("/", headers=h(b"nico:falsch")).status_code, 401)

    def test_anmeldeseite_und_abmelden(self):
        with open(os.path.join(_TMP, "passwort.txt"), "w") as f:
            f.write("geheim123")
        with open(os.path.join(_TMP, "benutzer.txt"), "w") as f:
            f.write("birgitgold")
        html = {"Accept": "text/html"}
        r = self.c.get("/", headers=html)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/anmelden", r.headers["Location"])
        self.assertEqual(self.c.get("/anmelden").status_code, 200)
        r = self.c.post("/anmelden", data={"benutzer": "x", "passwort": "geheim123"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("stimmt nicht", r.get_data(as_text=True))
        r = self.c.post("/anmelden", data={"benutzer": "birgitgold", "passwort": "geheim123"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.c.get("/", headers=html).status_code, 200)
        self.c.get("/abmelden")
        self.assertEqual(self.c.get("/", headers=html).status_code, 302)

    def test_backup(self):
        r = self.c.get("/backup.db")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data.startswith(b"SQLite format 3"))


if __name__ == "__main__":
    unittest.main()
