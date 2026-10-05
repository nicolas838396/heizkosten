"""Webseite: Uebersicht, Plaetze, Empfang, Abrechnung, PDF, Einstellungen."""

from __future__ import annotations

import datetime as dt
import hmac
import json
import os
import sqlite3
import time
import uuid

from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from . import billing, collector, db, report, schnell, wmbus_config
from .kc import HKV_TYPEN


def _secret_key() -> str:
    os.makedirs(db.DATA_DIR, exist_ok=True)
    pfad = os.path.join(db.DATA_DIR, "secret.key")
    if not os.path.exists(pfad):
        with open(pfad, "w") as f:
            f.write(os.urandom(24).hex())
    with open(pfad) as f:
        return f.read().strip()


def _passwort() -> str:
    env = os.environ.get("HEIZKOSTEN_PASSWORT", "").strip()
    if env:
        return env
    pfad = os.path.join(db.DATA_DIR, "passwort.txt")
    if os.path.exists(pfad):
        with open(pfad) as f:
            return f.read().strip()
    return ""


def _benutzer() -> str:
    """Erforderlicher Benutzername (leer = jeder Name ist erlaubt)."""
    env = os.environ.get("HEIZKOSTEN_BENUTZER", "").strip()
    if env:
        return env
    pfad = os.path.join(db.DATA_DIR, "benutzer.txt")
    if os.path.exists(pfad):
        with open(pfad) as f:
            return f.read().strip()
    return ""


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = _secret_key()
    app.config["MAX_CONTENT_LENGTH"] = 60 * 1024 * 1024
    app.permanent_session_lifetime = dt.timedelta(days=30)
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # ---------- Zugriffsschutz: Anmeldeseite (Cookie) oder HTTP-Basic fuer Programme ----------
    OFFEN = ("health", "static", "favicon", "anmelden", "abmelden")

    def _token(benutzer: str, pw: str) -> str:
        return hmac.new(
            app.secret_key.encode(), f"{benutzer}\0{pw}".encode(), "sha256"
        ).hexdigest()

    def _zugangsdaten_ok(name: str, pw_eingabe: str) -> bool:
        pw = _passwort()
        benutzer = _benutzer()
        return hmac.compare_digest(pw_eingabe.encode(), pw.encode()) and (
            not benutzer or hmac.compare_digest(name.encode(), benutzer.encode())
        )

    @app.before_request
    def pruefe_passwort():
        if request.endpoint in OFFEN:
            return None
        pw = _passwort()
        if not pw:
            return None
        auth = request.authorization
        if auth and _zugangsdaten_ok(auth.username or "", auth.password or ""):
            return None
        tok = session.get("zugang")
        if tok and hmac.compare_digest(str(tok), _token(_benutzer(), pw)):
            return None
        if "text/html" in request.headers.get("Accept", ""):
            return redirect(url_for("anmelden"))
        return Response(
            "Anmeldung erforderlich.", 401, {"WWW-Authenticate": 'Basic realm="Heizkosten"'}
        )

    @app.route("/anmelden", methods=["GET", "POST"])
    def anmelden():
        fehler = None
        if request.method == "POST":
            if _zugangsdaten_ok(request.form.get("benutzer", "").strip(), request.form.get("passwort", "")):
                session.clear()
                session["zugang"] = _token(_benutzer(), _passwort())
                session.permanent = True
                return redirect(url_for("index"))
            time.sleep(1)
            fehler = "Benutzername oder Passwort stimmt nicht."
        return render_template("login.html", fehler=fehler, benutzer_noetig=bool(_benutzer()))

    @app.route("/abmelden")
    def abmelden():
        session.clear()
        return redirect(url_for("anmelden"))

    @app.before_request
    def open_db():
        if request.endpoint in ("health", "static", "favicon"):
            return
        g.con = db.connect()

    @app.teardown_request
    def close_db(_exc):
        con = g.pop("con", None)
        if con is not None:
            try:
                con.commit()
            except sqlite3.Error:
                pass
            con.close()

    # ---------- Filter ----------
    @app.template_filter("zeit")
    def f_zeit(iso):
        if not iso:
            return "-"
        try:
            return dt.datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
        except ValueError:
            return iso

    @app.template_filter("vor")
    def f_vor(iso):
        if not iso:
            return "noch nie"
        try:
            sek = (dt.datetime.now() - dt.datetime.fromisoformat(iso)).total_seconds()
        except ValueError:
            return iso
        if sek < 90:
            return "gerade eben"
        if sek < 3600:
            return f"vor {int(sek // 60)} Min."
        if sek < 86400:
            return f"vor {int(sek // 3600)} Std."
        return f"vor {int(sek // 86400)} Tagen"

    app.add_template_filter(report.eur, "eur")
    app.add_template_filter(lambda v, n=2: report.zahl(v, n), "zahl")
    app.add_template_filter(report.datum, "datum")

    @app.context_processor
    def global_ctx():
        con = g.get("con")
        return {
            "demo": db.demo_active(),
            "dirty": bool(con and db.get_setting(con, "config_dirty", "") == "1"),
            "nav": [
                ("index", "Übersicht"),
                ("plaetze", "Plätze"),
                ("empfang", "Empfang"),
                ("abrechnung", "Abrechnung"),
                ("einstellungen", "Mehr"),
            ],
        }

    # ---------- Hilfsfunktionen ----------
    def platz_status(p, gesehen, messungen):
        if not p["geraet_id"]:
            return "geplant", "Geplant"
        if gesehen is None:
            return "wartet", "Zugeordnet, noch nichts empfangen"
        if not p["aes_key"] and messungen == 0:
            return "warn", "Empfangen, aber Schlüssel fehlt"
        try:
            alter = (dt.datetime.now() - dt.datetime.fromisoformat(gesehen["zuletzt"])).total_seconds()
        except ValueError:
            alter = 0
        if alter > 48 * 3600:
            return "warn", "Seit über 48 Std. keine Meldung"
        return "ok", "Empfang ok"

    def lade_plaetze():
        con = g.con
        gesehen = {r["geraet_id"]: r for r in con.execute("SELECT * FROM gesehen")}
        letzte = {r["geraet_id"]: r for r in con.execute("SELECT * FROM letzte")}
        anzahl = {
            r["geraet_id"]: r["n"]
            for r in con.execute("SELECT geraet_id, COUNT(*) AS n FROM messung GROUP BY geraet_id")
        }
        wohnungen = {w["id"]: w for w in con.execute("SELECT * FROM wohnung ORDER BY sort, id")}
        ergebnis = []
        for p in con.execute("SELECT * FROM platz ORDER BY wohnung_id IS NULL, wohnung_id, typ DESC, raum, id"):
            d = dict(p)
            ges = gesehen.get(p["geraet_id"]) if p["geraet_id"] else None
            d["status"], d["status_text"] = platz_status(p, ges, anzahl.get(p["geraet_id"], 0))
            d["zuletzt"] = ges["zuletzt"] if ges else None
            d["rssi"] = ges["rssi"] if ges else None
            d["wohnung_name"] = (
                wohnungen[p["wohnung_id"]]["bezeichnung"] or p["wohnung_id"]
                if p["wohnung_id"] in wohnungen
                else "Ohne Wohnung"
            )
            d["hat_messwerte"] = anzahl.get(p["geraet_id"], 0)
            d["roh_ts"] = letzte[p["geraet_id"]]["ts"] if p["geraet_id"] in letzte else None
            ergebnis.append(d)
        return ergebnis, list(wohnungen.values())

    def markiere_dirty():
        db.set_setting(g.con, "config_dirty", "1")
        try:
            wmbus_config.write_meter_files(g.con)
        except OSError:
            pass

    def zahl_oder_none(raw):
        raw = (raw or "").strip().replace(",", ".")
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    # ---------- Seiten ----------
    @app.route("/health")
    def health():
        return "ok"

    @app.route("/favicon.ico")
    def favicon():
        return Response(status=204)

    @app.route("/")
    def index():
        plaetze, wohnungen = lade_plaetze()
        gruppen = {}
        for p in plaetze:
            gruppen.setdefault(p["wohnung_name"], []).append(p)
        stat = {
            "gesamt": len(plaetze),
            "zugeordnet": sum(1 for p in plaetze if p["geraet_id"]),
            "ok": sum(1 for p in plaetze if p["status"] == "ok"),
            "warn": sum(1 for p in plaetze if p["status"] == "warn"),
        }
        neu = g.con.execute(
            "SELECT COUNT(*) AS n FROM gesehen WHERE geraet_id NOT IN "
            "(SELECT geraet_id FROM platz WHERE geraet_id IS NOT NULL)"
        ).fetchone()["n"]
        letzter = g.con.execute("SELECT MAX(zuletzt) AS z FROM gesehen").fetchone()["z"]
        return render_template(
            "index.html", gruppen=gruppen, stat=stat, neu=neu, letzter=letzter, status=collector.status
        )

    @app.route("/plaetze")
    def plaetze():
        liste, wohnungen = lade_plaetze()
        gruppen = {}
        for p in liste:
            gruppen.setdefault(p["wohnung_name"], []).append(p)
        return render_template("plaetze.html", gruppen=gruppen)

    def _platz_formdaten(form):
        typ = form.get("typ", "HKV")
        if typ not in ("HKV", "WMZ"):
            typ = "HKV"
        geraet_id = db.normalize_id(form.get("geraet_id", "")) or None
        return {
            "typ": typ,
            "wohnung_id": form.get("wohnung_id") or None,
            "raum": form.get("raum", "").strip(),
            "bezeichnung": form.get("bezeichnung", "").strip(),
            "heizkreis": (form.get("heizkreis", "1").strip() or "1").upper(),
            "hkv_typ": form.get("hkv_typ", "").strip(),
            "hoehe_cm": zahl_oder_none(form.get("hoehe_cm")),
            "laenge_cm": zahl_oder_none(form.get("laenge_cm")),
            "kc_manuell": zahl_oder_none(form.get("kc_manuell")),
            "geraet_id": geraet_id,
            "aes_key": db.normalize_key(form.get("aes_key", "")),
            "notiz": form.get("notiz", "").strip(),
        }

    def _form_ctx(platz):
        wohnungen = g.con.execute("SELECT * FROM wohnung ORDER BY sort, id").fetchall()
        frei = g.con.execute(
            "SELECT * FROM gesehen WHERE geraet_id NOT IN "
            "(SELECT geraet_id FROM platz WHERE geraet_id IS NOT NULL) ORDER BY zuletzt DESC LIMIT 30"
        ).fetchall()
        return {"platz": platz, "wohnungen": wohnungen, "typen": HKV_TYPEN, "frei": frei}

    @app.route("/platz/neu", methods=["GET", "POST"])
    def platz_neu():
        if request.method == "POST":
            d = _platz_formdaten(request.form)
            try:
                g.con.execute(
                    "INSERT INTO platz (typ, wohnung_id, raum, bezeichnung, heizkreis, hkv_typ, hoehe_cm, laenge_cm, "
                    "kc_manuell, geraet_id, aes_key, notiz, erstellt) VALUES (:typ, :wohnung_id, :raum, :bezeichnung, "
                    ":heizkreis, :hkv_typ, :hoehe_cm, :laenge_cm, :kc_manuell, :geraet_id, :aes_key, :notiz, :erstellt)",
                    {**d, "erstellt": db.now_iso()},
                )
            except sqlite3.IntegrityError:
                flash("Diese Geräte-Nummer ist schon einem anderen Platz zugeordnet.", "fehler")
                return render_template("platz_form.html", **_form_ctx(d)), 400
            markiere_dirty()
            flash("Platz angelegt.", "ok")
            return redirect(url_for("plaetze"))
        start = {"typ": request.args.get("typ", "HKV"), "wohnung_id": request.args.get("wohnung_id"), "heizkreis": "1"}
        return render_template("platz_form.html", **_form_ctx(start))

    @app.route("/platz/<int:pid>", methods=["GET", "POST"])
    def platz_bearbeiten(pid):
        row = g.con.execute("SELECT * FROM platz WHERE id = ?", (pid,)).fetchone()
        if row is None:
            abort(404)
        if request.method == "POST":
            d = _platz_formdaten(request.form)
            try:
                g.con.execute(
                    "UPDATE platz SET typ=:typ, wohnung_id=:wohnung_id, raum=:raum, bezeichnung=:bezeichnung, "
                    "heizkreis=:heizkreis, hkv_typ=:hkv_typ, hoehe_cm=:hoehe_cm, laenge_cm=:laenge_cm, "
                    "kc_manuell=:kc_manuell, geraet_id=:geraet_id, aes_key=:aes_key, notiz=:notiz WHERE id=:id",
                    {**d, "id": pid},
                )
            except sqlite3.IntegrityError:
                flash("Diese Geräte-Nummer ist schon einem anderen Platz zugeordnet.", "fehler")
                return render_template("platz_form.html", **_form_ctx({**d, "id": pid})), 400
            markiere_dirty()
            flash("Gespeichert.", "ok")
            return redirect(url_for("plaetze"))
        return render_template("platz_form.html", **_form_ctx(dict(row)))

    @app.route("/platz/<int:pid>/loeschen", methods=["POST"])
    def platz_loeschen(pid):
        g.con.execute("DELETE FROM platz WHERE id = ?", (pid,))
        markiere_dirty()
        flash("Platz gelöscht (empfangene Messwerte bleiben erhalten).", "ok")
        return redirect(url_for("plaetze"))

    @app.route("/platz/<int:pid>/messwerte", methods=["GET", "POST"])
    def messwerte(pid):
        p = g.con.execute("SELECT * FROM platz WHERE id = ?", (pid,)).fetchone()
        if p is None:
            abort(404)
        if request.method == "POST":
            wert = zahl_oder_none(request.form.get("wert"))
            datum = request.form.get("datum", "").strip()
            if not p["geraet_id"]:
                flash("Erst eine Geräte-Nummer zuordnen, dann können Werte erfasst werden.", "fehler")
            elif wert is None or not datum:
                flash("Datum und Wert angeben.", "fehler")
            else:
                try:
                    ts = dt.datetime.fromisoformat(datum + "T12:00:00").isoformat()
                except ValueError:
                    ts = None
                if ts is None:
                    flash("Ungültiges Datum.", "fehler")
                else:
                    g.con.execute(
                        "INSERT OR REPLACE INTO messung (geraet_id, ts, wert, einheit, quelle) VALUES (?, ?, ?, ?, 'manuell')",
                        (p["geraet_id"], ts, wert, "kWh" if p["typ"] == "WMZ" else "Einheiten"),
                    )
                    flash("Messwert gespeichert.", "ok")
            return redirect(url_for("messwerte", pid=pid))
        rows = []
        roh = None
        if p["geraet_id"]:
            rows = g.con.execute(
                "SELECT * FROM messung WHERE geraet_id = ? ORDER BY ts DESC LIMIT 200", (p["geraet_id"],)
            ).fetchall()
            letzte = g.con.execute("SELECT * FROM letzte WHERE geraet_id = ?", (p["geraet_id"],)).fetchone()
            if letzte:
                try:
                    roh = json.dumps(json.loads(letzte["roh"]), indent=2, ensure_ascii=False)
                except ValueError:
                    roh = letzte["roh"]
        return render_template("messwerte.html", platz=p, rows=rows, roh=roh, heute=dt.date.today().isoformat())

    @app.route("/plaetze/schnell", methods=["POST"])
    def plaetze_schnell():
        text = request.form.get("liste", "")
        eintraege = schnell.parse(text)
        if not eintraege:
            flash("Keine Zeilen erkannt. Format: 'EG: Wohnzimmer 2, Küche'.", "fehler")
            return redirect(url_for("plaetze"))
        wohnungen = [dict(w) for w in g.con.execute("SELECT id, bezeichnung FROM wohnung")]
        vorhandene = {w["id"] for w in wohnungen}
        angelegt = 0
        for label, raum, anzahl in eintraege:
            wid = schnell.finde_wohnung(label, wohnungen)
            if wid is None:
                wid = schnell.neue_wohnungs_id(label, vorhandene)
                vorhandene.add(wid)
                g.con.execute(
                    "INSERT INTO wohnung (id, bezeichnung, sort) VALUES (?, ?, 99)", (wid, label)
                )
                wohnungen.append({"id": wid, "bezeichnung": label})
            for i in range(1, anzahl + 1):
                bez = f"Heizkörper {raum}" + (f" {i}" if anzahl > 1 else "")
                g.con.execute(
                    "INSERT INTO platz (typ, wohnung_id, raum, bezeichnung, heizkreis, erstellt) "
                    "VALUES ('HKV', ?, ?, ?, '1', ?)",
                    (wid, raum, bez, db.now_iso()),
                )
                angelegt += 1
        flash(f"{angelegt} Plätze angelegt.", "ok")
        return redirect(url_for("plaetze"))

    @app.route("/wohnungen", methods=["GET", "POST"])
    def wohnungen():
        if request.method == "POST":
            for w in g.con.execute("SELECT id FROM wohnung").fetchall():
                wid = w["id"]
                if f"bez_{wid}" not in request.form:
                    continue
                g.con.execute(
                    "UPDATE wohnung SET bezeichnung=?, flaeche_qm=?, nutzung=?, sort=? WHERE id=?",
                    (
                        request.form.get(f"bez_{wid}", "").strip(),
                        zahl_oder_none(request.form.get(f"qm_{wid}")),
                        request.form.get(f"nutzung_{wid}", "").strip(),
                        int(zahl_oder_none(request.form.get(f"sort_{wid}")) or 0),
                        wid,
                    ),
                )
            flash("Wohnungen gespeichert.", "ok")
            return redirect(url_for("wohnungen"))
        rows = g.con.execute(
            "SELECT w.*, (SELECT COUNT(*) FROM platz p WHERE p.wohnung_id = w.id) AS plaetze "
            "FROM wohnung w ORDER BY sort, id"
        ).fetchall()
        return render_template("wohnungen.html", rows=rows)

    @app.route("/wohnung/neu", methods=["POST"])
    def wohnung_neu():
        bez = request.form.get("bezeichnung", "").strip()
        if not bez:
            flash("Bezeichnung angeben.", "fehler")
            return redirect(url_for("wohnungen"))
        vorhandene = {r["id"] for r in g.con.execute("SELECT id FROM wohnung")}
        wid = schnell.neue_wohnungs_id(bez, vorhandene)
        g.con.execute("INSERT INTO wohnung (id, bezeichnung, sort) VALUES (?, ?, 99)", (wid, bez))
        flash("Wohnung angelegt.", "ok")
        return redirect(url_for("wohnungen"))

    @app.route("/wohnung/<wid>/loeschen", methods=["POST"])
    def wohnung_loeschen(wid):
        g.con.execute("DELETE FROM wohnung WHERE id = ?", (wid,))
        flash("Wohnung gelöscht; ihre Plätze sind jetzt ohne Wohnung.", "ok")
        return redirect(url_for("wohnungen"))

    @app.route("/empfang")
    def empfang():
        gesehen = g.con.execute(
            "SELECT s.*, p.id AS platz_id, p.raum AS platz_raum, p.typ AS platz_typ, p.wohnung_id AS platz_wohnung "
            "FROM gesehen s LEFT JOIN platz p ON p.geraet_id = s.geraet_id ORDER BY s.zuletzt DESC LIMIT 300"
        ).fetchall()
        frei = g.con.execute(
            "SELECT p.id, p.typ, p.raum, p.bezeichnung, w.bezeichnung AS wohnung FROM platz p "
            "LEFT JOIN wohnung w ON w.id = p.wohnung_id WHERE p.geraet_id IS NULL ORDER BY w.sort, p.raum, p.id"
        ).fetchall()
        return render_template(
            "empfang.html", gesehen=gesehen, frei=frei, status=collector.status,
            dienst=wmbus_config.service_status(),
        )

    @app.route("/empfang/zuordnen", methods=["POST"])
    def empfang_zuordnen():
        geraet_id = db.normalize_id(request.form.get("geraet_id", ""))
        pid = request.form.get("platz_id", "")
        if not geraet_id or not pid.isdigit():
            flash("Bitte einen Platz auswählen.", "fehler")
            return redirect(url_for("empfang"))
        try:
            g.con.execute("UPDATE platz SET geraet_id = ? WHERE id = ?", (geraet_id, int(pid)))
        except sqlite3.IntegrityError:
            flash("Diese Geräte-Nummer ist schon zugeordnet.", "fehler")
            return redirect(url_for("empfang"))
        markiere_dirty()
        flash("Zugeordnet. Falls das Gerät einen Schlüssel braucht, trag ihn beim Platz ein.", "ok")
        return redirect(url_for("platz_bearbeiten", pid=int(pid)))

    ABR_FELDER = (
        "gesamtkosten", "wasserkosten", "verbrauchsanteil", "abrechnung_von", "abrechnung_bis",
        "ww_verbrauchsanteil", "ww_temperatur", "ww_pauschal_prozent",
    )

    @app.route("/abrechnung", methods=["GET", "POST"])
    def abrechnung():
        if request.method == "POST":
            for key in ABR_FELDER:
                if key in request.form:
                    db.set_setting(g.con, key, request.form.get(key, "").strip())
            flash("Eingaben gespeichert.", "ok")
            return redirect(url_for("abrechnung"))
        einst = {k: db.get_setting(g.con, k) for k in ABR_FELDER}
        fehler, ergebnis = None, None
        try:
            ergebnis = billing.lade_und_berechne(g.con)
        except ValueError as exc:
            fehler = str(exc)
        anzahl_zaehler = g.con.execute("SELECT COUNT(*) FROM zaehler").fetchone()[0]
        return render_template(
            "abrechnung.html", einst=einst, ergebnis=ergebnis, fehler=fehler, anzahl_zaehler=anzahl_zaehler
        )

    # ---------- Wasserzaehler und Ablesung (Foto + Zahl) ----------
    FOTO_ENDUNGEN = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}

    def speichere_foto(datei, ablesung_id):
        if datei is None or not datei.filename:
            return ""
        endung = os.path.splitext(datei.filename)[1].lower()
        if endung not in FOTO_ENDUNGEN:
            endung = ".jpg"
        name = f"a{ablesung_id}_{uuid.uuid4().hex[:8]}{endung}"
        os.makedirs(db.foto_dir(), exist_ok=True)
        datei.save(os.path.join(db.foto_dir(), name))
        return name

    def lade_zaehler_mit_letzter():
        wohnungen = g.con.execute("SELECT * FROM wohnung ORDER BY sort, id").fetchall()
        zaehler = []
        for z in g.con.execute("SELECT * FROM zaehler ORDER BY art DESC, id"):
            d = dict(z)
            letzte = g.con.execute(
                "SELECT datum, wert FROM ablesung WHERE zaehler_id = ? ORDER BY datum DESC, id DESC LIMIT 1",
                (z["id"],),
            ).fetchone()
            d["letzte"] = dict(letzte) if letzte else None
            zaehler.append(d)
        return wohnungen, zaehler

    @app.route("/ablesung", methods=["GET", "POST"])
    def ablesung():
        wohnungen, zaehler = lade_zaehler_mit_letzter()
        if request.method == "POST":
            datum = request.form.get("datum", "").strip() or dt.date.today().isoformat()
            try:
                dt.date.fromisoformat(datum)
            except ValueError:
                flash("Datum ungültig.", "fehler")
                return redirect(url_for("ablesung"))
            gespeichert, auffaellig = 0, []
            for z in zaehler:
                wert = zahl_oder_none(request.form.get(f"wert_{z['id']}"))
                if wert is None:
                    continue
                if z["letzte"] and wert < z["letzte"]["wert"] and z["letzte"]["datum"] <= datum:
                    auffaellig.append(z["bezeichnung"] or f"Zähler {z['id']}")
                cur = g.con.execute(
                    "INSERT INTO ablesung (zaehler_id, datum, wert, erstellt) VALUES (?, ?, ?, ?)",
                    (z["id"], datum, wert, db.now_iso()),
                )
                foto = speichere_foto(request.files.get(f"foto_{z['id']}"), cur.lastrowid)
                if foto:
                    g.con.execute("UPDATE ablesung SET foto = ? WHERE id = ?", (foto, cur.lastrowid))
                gespeichert += 1
            if not gespeichert:
                flash("Keine Zählerstände eingetragen.", "hinweis")
                return redirect(url_for("ablesung"))
            flash(f"{gespeichert} Zählerstand/-stände gespeichert.", "ok")
            if auffaellig:
                flash("Stand niedriger als der vorherige bei: " + ", ".join(auffaellig) + ". Bitte prüfen.", "hinweis")
            return redirect(url_for("abrechnung") if request.form.get("weiter") else url_for("ablesung"))
        gruppen = []
        for w in wohnungen:
            gruppen.append((w["bezeichnung"] or w["id"], w["id"], [z for z in zaehler if z["wohnung_id"] == w["id"]]))
        haus = [z for z in zaehler if not z["wohnung_id"]]
        return render_template(
            "ablesung.html",
            gruppen=gruppen,
            haus=haus,
            wohnungen=wohnungen,
            heute=dt.date.today().isoformat(),
            arten=db.ZAEHLER_ARTEN,
            hat_zaehler=bool(zaehler),
        )

    @app.route("/zaehler/schnell", methods=["POST"])
    def zaehler_schnell():
        neu = 0
        for w in g.con.execute("SELECT id, bezeichnung FROM wohnung ORDER BY sort, id").fetchall():
            for art, feld, name in (("WARM", "warm", "Warmwasser"), ("KALT", "kalt", "Kaltwasser")):
                soll = int(zahl_oder_none(request.form.get(f"{feld}_{w['id']}")) or 0)
                soll = max(0, min(soll, 10))
                haben = g.con.execute(
                    "SELECT COUNT(*) FROM zaehler WHERE art = ? AND wohnung_id = ?", (art, w["id"])
                ).fetchone()[0]
                for i in range(haben + 1, soll + 1):
                    g.con.execute(
                        "INSERT INTO zaehler (art, wohnung_id, bezeichnung, einheit, erstellt) VALUES (?, ?, ?, 'm³', ?)",
                        (art, w["id"], f"{name} {i}", db.now_iso()),
                    )
                    neu += 1
        if request.form.get("ww_waerme"):
            if not g.con.execute("SELECT 1 FROM zaehler WHERE art = 'WW_WAERME'").fetchone():
                g.con.execute(
                    "INSERT INTO zaehler (art, wohnung_id, bezeichnung, einheit, erstellt) "
                    "VALUES ('WW_WAERME', NULL, 'Wärmemengenzähler Warmwasser', 'kWh', ?)",
                    (db.now_iso(),),
                )
                neu += 1
        flash(f"{neu} Zähler angelegt." if neu else "Nichts Neues angelegt.", "ok" if neu else "hinweis")
        return redirect(url_for("ablesung"))

    @app.route("/zaehler/neu", methods=["POST"])
    def zaehler_neu():
        art = request.form.get("art", "WARM")
        if art not in db.ZAEHLER_ARTEN:
            art = "WARM"
        wid = request.form.get("wohnung_id") or None
        if art == "WW_WAERME":
            wid = None
        einheit = "kWh" if art == "WW_WAERME" else "m³"
        bez = request.form.get("bezeichnung", "").strip() or db.ZAEHLER_ARTEN[art].split(" (")[0]
        cur = g.con.execute(
            "INSERT INTO zaehler (art, wohnung_id, bezeichnung, einheit, erstellt) VALUES (?, ?, ?, ?, ?)",
            (art, wid, bez, einheit, db.now_iso()),
        )
        flash("Zähler angelegt.", "ok")
        return redirect(url_for("zaehler_bearbeiten", zid=cur.lastrowid))

    @app.route("/zaehler/<int:zid>", methods=["GET", "POST"])
    def zaehler_bearbeiten(zid):
        z = g.con.execute("SELECT * FROM zaehler WHERE id = ?", (zid,)).fetchone()
        if z is None:
            abort(404)
        if request.method == "POST":
            einheit = request.form.get("einheit", z["einheit"])
            if z["art"] == "WW_WAERME" and einheit not in ("kWh", "MWh", "GJ"):
                einheit = "kWh"
            if z["art"] != "WW_WAERME":
                einheit = "m³"
            g.con.execute(
                "UPDATE zaehler SET bezeichnung=?, wohnung_id=?, einheit=?, notiz=? WHERE id=?",
                (
                    request.form.get("bezeichnung", "").strip(),
                    (request.form.get("wohnung_id") or None) if z["art"] != "WW_WAERME" else None,
                    einheit,
                    request.form.get("notiz", "").strip(),
                    zid,
                ),
            )
            flash("Gespeichert.", "ok")
            return redirect(url_for("zaehler_bearbeiten", zid=zid))
        wohnungen = g.con.execute("SELECT * FROM wohnung ORDER BY sort, id").fetchall()
        hist = g.con.execute(
            "SELECT * FROM ablesung WHERE zaehler_id = ? ORDER BY datum DESC, id DESC", (zid,)
        ).fetchall()
        return render_template(
            "zaehler.html", z=z, wohnungen=wohnungen, hist=hist, arten=db.ZAEHLER_ARTEN
        )

    @app.route("/zaehler/<int:zid>/loeschen", methods=["POST"])
    def zaehler_loeschen(zid):
        for r in g.con.execute("SELECT foto FROM ablesung WHERE zaehler_id = ?", (zid,)).fetchall():
            if r["foto"]:
                try:
                    os.remove(os.path.join(db.foto_dir(), os.path.basename(r["foto"])))
                except OSError:
                    pass
        g.con.execute("DELETE FROM zaehler WHERE id = ?", (zid,))
        flash("Zähler samt Ablesungen gelöscht.", "ok")
        return redirect(url_for("ablesung"))

    @app.route("/ablesung/<int:aid>/loeschen", methods=["POST"])
    def ablesung_loeschen(aid):
        r = g.con.execute("SELECT zaehler_id, foto FROM ablesung WHERE id = ?", (aid,)).fetchone()
        if r is None:
            abort(404)
        if r["foto"]:
            try:
                os.remove(os.path.join(db.foto_dir(), os.path.basename(r["foto"])))
            except OSError:
                pass
        g.con.execute("DELETE FROM ablesung WHERE id = ?", (aid,))
        flash("Ablesung gelöscht.", "ok")
        return redirect(url_for("zaehler_bearbeiten", zid=r["zaehler_id"]))

    @app.route("/foto/<int:aid>")
    def foto(aid):
        r = g.con.execute("SELECT foto FROM ablesung WHERE id = ?", (aid,)).fetchone()
        if r is None or not r["foto"]:
            abort(404)
        pfad = os.path.join(db.foto_dir(), os.path.basename(r["foto"]))
        if not os.path.exists(pfad):
            abort(404)
        return send_file(pfad)

    @app.route("/pdf/<wid>.pdf")
    def pdf(wid):
        try:
            ergebnis = billing.lade_und_berechne(g.con)
            data = report.wohnung_pdf(
                ergebnis,
                wid,
                db.get_setting(g.con, "objekt"),
                db.get_setting(g.con, "abrechnung_titel"),
            )
        except KeyError:
            abort(404)
        except ValueError as exc:
            flash(str(exc), "fehler")
            return redirect(url_for("abrechnung"))
        return Response(
            data,
            mimetype="application/pdf",
            headers={"Content-Disposition": f'inline; filename="Abrechnung_{wid}.pdf"'},
        )

    @app.route("/einstellungen", methods=["GET", "POST"])
    def einstellungen():
        if request.method == "POST":
            aktion = request.form.get("aktion", "")
            if aktion == "texte":
                db.set_setting(g.con, "objekt", request.form.get("objekt", "").strip())
                db.set_setting(g.con, "abrechnung_titel", request.form.get("titel", "").strip())
                flash("Gespeichert.", "ok")
            elif aktion == "uebernehmen":
                try:
                    res = wmbus_config.write_meter_files(g.con)
                    ok, msg = wmbus_config.restart_service()
                except OSError as exc:
                    ok, msg, res = False, f"Konfiguration konnte nicht geschrieben werden: {exc}", None
                if ok:
                    db.set_setting(g.con, "config_dirty", "0")
                    flash(f"{res['anzahl']} Geräte übernommen, {msg}.", "ok")
                    if res["ohne_schluessel"]:
                        flash(f"Ohne Schlüssel (nur ID-Erkennung): {', '.join(res['ohne_schluessel'])}", "hinweis")
                else:
                    flash(f"Nicht übernommen: {msg}", "fehler")
            elif aktion == "demo":
                g.con.commit()
                db.set_demo(request.form.get("an") == "1")
                flash("Demo-Ansicht " + ("eingeschaltet" if db.demo_active() else "ausgeschaltet") + ".", "ok")
            return redirect(url_for("einstellungen"))
        return render_template(
            "einstellungen.html",
            objekt=db.get_setting(g.con, "objekt"),
            titel=db.get_setting(g.con, "abrechnung_titel"),
            status=collector.status,
            dienst=wmbus_config.service_status(),
            db_pfad=db.db_path(),
        )

    @app.route("/backup.db")
    def backup():
        g.con.commit()
        return send_file(db.db_path(), as_attachment=True, download_name="heizkosten-backup.db")

    return app
