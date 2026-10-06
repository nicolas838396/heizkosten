"""Feste Stammdaten des Hauses (nur per Code aenderbar, in der App schreibgeschuetzt).

Aenderungen: diese Datei bearbeiten, committen, auf dem Pi `git pull` und
`sudo systemctl restart heizkosten`. Beim Start gleicht die App die Datenbank
mit dieser Liste ab. Geraetenummer, AES-Schluessel, Ablesungen und Kosten
bleiben davon unberuehrt und sind weiter in der App eingebbar.

flaeche_qm: beheizte Wohnflaeche ohne Balkone (None = noch nicht eingetragen).
leistung_w: Normwaermeleistung des Heizkoerpers in Watt (laut Rechnung/Liste).
"""

WOHNUNGEN = [
    # id, Bezeichnung, beheizte Flaeche m2, Reihenfolge
    ("EG", "Erdgeschoss", None, 1),
    ("1OG", "1. Obergeschoss", None, 2),
    ("DG", "Dachgeschoss", None, 3),
    ("KELLER", "Kellergeschoss", None, 4),
]

# schluessel (dauerhaft eindeutig), Wohnung, Raum, Bezeichnung, Heizkreis,
# Hoehe cm, Laenge cm, Watt, Notiz
HKV = [
    ("KELLER-1", "KELLER", "Bad", "Badheizkörper", "1", 80, 50, 407,
     "Neuer Heizkörper, Wattzahl laut Rechnung."),
    ("KELLER-2", "KELLER", "Keller (Raum noch eintragen)", "Heizkörper 2", "1", 54, 180, 1627,
     "Neuer Heizkörper, 1,80 m × 0,54 m, Wattzahl laut Rechnung."),
]

# Waermemengenzaehler im Heizungsraum (Geraetenummer wird in der App eingetragen)
WMZ = [
    ("WMZ-1", "Heizungsraum", "Wärmemengenzähler Heizkreis 1", "1"),
    ("WMZ-2", "Heizungsraum", "Wärmemengenzähler Heizkreis 2", "2"),
]


def sync(con):
    """Datenbank an die festen Stammdaten angleichen (idempotent)."""
    for wid, bez, qm, sort in WOHNUNGEN:
        row = con.execute("SELECT bezeichnung, flaeche_qm, sort FROM wohnung WHERE id=?", (wid,)).fetchone()
        if row is None:
            con.execute("INSERT INTO wohnung (id, bezeichnung, flaeche_qm, sort) VALUES (?,?,?,?)", (wid, bez, qm, sort))
        elif (row["bezeichnung"], row["flaeche_qm"], row["sort"]) != (bez, qm, sort):
            con.execute("UPDATE wohnung SET bezeichnung=?, flaeche_qm=?, sort=? WHERE id=?", (bez, qm, sort, wid))

    def upsert(key, werte):
        row = con.execute("SELECT id FROM platz WHERE fest_key=?", (key,)).fetchone()
        if row is None and werte["typ"] == "WMZ":  # vorhandenen Standard-WMZ uebernehmen
            row = con.execute(
                "SELECT id FROM platz WHERE fest_key IS NULL AND typ='WMZ' AND heizkreis=? ORDER BY id LIMIT 1",
                (werte["heizkreis"],),
            ).fetchone()
        spalten = ["typ", "wohnung_id", "raum", "bezeichnung", "heizkreis", "hoehe_cm", "laenge_cm", "leistung_w", "notiz"]
        if row is None:
            from .db import now_iso
            con.execute(
                f"INSERT INTO platz (fest_key, erstellt, {','.join(spalten)}) VALUES (?,?,{','.join('?' * len(spalten))})",
                [key, now_iso()] + [werte[s] for s in spalten],
            )
        else:
            con.execute(
                f"UPDATE platz SET fest_key=?, {','.join(s + '=?' for s in spalten)} WHERE id=?",
                [key] + [werte[s] for s in spalten] + [row["id"]],
            )

    for key, wid, raum, bez, kreis, h, l, w, notiz in HKV:
        upsert(key, dict(typ="HKV", wohnung_id=wid, raum=raum, bezeichnung=bez, heizkreis=kreis,
                         hoehe_cm=h, laenge_cm=l, leistung_w=w, notiz=notiz))
    for key, raum, bez, kreis in WMZ:
        upsert(key, dict(typ="WMZ", wohnung_id=None, raum=raum, bezeichnung=bez, heizkreis=kreis,
                         hoehe_cm=None, laenge_cm=None, leistung_w=None, notiz=""))
