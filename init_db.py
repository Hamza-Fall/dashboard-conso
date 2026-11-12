"""
init_db.py : crée la base SQLite et la remplit à partir des CSV du dossier data/.

- En ligne de commande :   python init_db.py      (recrée la base et vérifie le chargement)
- Depuis l'application :   init_db.construire_base()   (appelé au démarrage de app.py)

La base `consommation.db` n'est jamais versionnée : elle est régénérée à partir des CSV.
"""
import glob
import os
import sqlite3
import time

import numpy as np
import pandas as pd

import db

BASE = os.path.dirname(os.path.abspath(__file__))
DOSSIER_CSV = os.path.join(BASE, "data")

# Grille tarifaire (c€/kWh) : (heures pleines 06h-22h, heures creuses 22h-06h)
TARIFS = {
    "Agriculteur 1": (9.52, 5.28),   "Agriculteur 2": (13.03, 9.62),
    "Agriculteur 3": (15.31, 10.08), "Agriculteur 4": (14.17, 10.07),
    "Industriel 1": (23.12, 17.15),  "Industriel 2": (33.54, 17.15),
    "Industriel 3": (16.27, 11.08),  "Industriel 4": (12.38, 9.25),
    "Site Publique 1": (14.21, 11.32), "Site Publique 2": (13.98, 7.67),
}
# Positions SUPPOSÉES (non fournies dans les données), Île-de-France
COORDS = {
    "Agriculteur 1": (48.560, 3.300),  "Agriculteur 2": (48.970, 2.870),
    "Agriculteur 3": (48.810, 3.090),  "Agriculteur 4": (48.640, 1.830),
    "Industriel 1": (48.930, 2.290),   "Industriel 2": (48.790, 2.390),
    "Industriel 3": (48.970, 2.520),   "Industriel 4": (48.590, 2.580),
    "Site Publique 1": (48.857, 2.352), "Site Publique 2": (48.802, 2.130),
}

SCHEMA = """
CREATE TABLE consommateurs (
    id_consommateur TEXT PRIMARY KEY,
    type            TEXT NOT NULL,
    latitude        REAL NOT NULL,
    longitude       REAL NOT NULL,
    id_contrat      TEXT NOT NULL
);

CREATE TABLE releves (
    id_releve       INTEGER PRIMARY KEY AUTOINCREMENT,
    id_consommateur TEXT NOT NULL REFERENCES consommateurs(id_consommateur),
    horodatage      TEXT NOT NULL,          -- 'AAAA-MM-JJ HH:MM:SS'
    puissance_kw    REAL NOT NULL           -- relevé toutes les 5 minutes
);

CREATE TABLE tarifs (
    id_tarif    INTEGER PRIMARY KEY AUTOINCREMENT,
    id_contrat  TEXT NOT NULL,
    plage       TEXT NOT NULL CHECK (plage IN ('HP', 'HC')),
    heure_debut INTEGER NOT NULL,           -- heure incluse
    heure_fin   INTEGER NOT NULL,           -- heure exclue (HC : 22 -> 6 passe minuit)
    prix_kwh    REAL NOT NULL               -- en euros par kWh
);

CREATE INDEX idx_releves_consommateur ON releves(id_consommateur);
CREATE INDEX idx_tarifs_contrat       ON tarifs(id_contrat);
"""


def type_of(nom):
    return nom.split(" ")[0].replace("Site", "Site public")


def lister_csv():
    fichiers = sorted(glob.glob(os.path.join(DOSSIER_CSV, "*.csv")))
    if len(fichiers) != len(TARIFS):
        raise FileNotFoundError(
            f"{len(fichiers)} fichier(s) CSV trouvé(s) dans {DOSSIER_CSV} ({len(TARIFS)} attendus). "
            "Lancez d'abord : python convertir_en_csv.py")
    return fichiers


def construire_base(verifier=True, afficher=False):
    """Recrée entièrement la base à partir des CSV. La base est écrite dans un fichier temporaire
    puis renommée : l'ancienne base n'est jamais laissée à moitié construite."""
    t0 = time.time()
    fichiers = lister_csv()
    temporaire = db.DB_PATH + ".tmp"
    if os.path.exists(temporaire):
        os.remove(temporaire)

    conn = sqlite3.connect(temporaire)
    reference = {}
    try:
        conn.execute("PRAGMA journal_mode = OFF")      # base jetable, régénérable : on privilégie la vitesse
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA)

        # 1) consommateurs et tarifs (un contrat par consommateur, 2 plages HP/HC par contrat)
        contrat = {nom: "CT-" + nom.upper().replace(" ", "-") for nom in TARIFS}
        conn.executemany(
            "INSERT INTO consommateurs (id_consommateur, type, latitude, longitude, id_contrat) VALUES (?,?,?,?,?)",
            [(nom, type_of(nom), COORDS[nom][0], COORDS[nom][1], contrat[nom]) for nom in TARIFS])
        lignes_tarifs = []
        for nom, (hp, hc) in TARIFS.items():
            lignes_tarifs.append((contrat[nom], "HP", 6, 22, round(hp / 100, 6)))     # 06h -> 22h
            lignes_tarifs.append((contrat[nom], "HC", 22, 6, round(hc / 100, 6)))     # 22h -> 06h (passe minuit)
        conn.executemany(
            "INSERT INTO tarifs (id_contrat, plage, heure_debut, heure_fin, prix_kwh) VALUES (?,?,?,?,?)", lignes_tarifs)

        # 2) relevés : un CSV par consommateur
        for path in fichiers:
            nom = os.path.splitext(os.path.basename(path))[0].replace("_", " ")
            if nom not in TARIFS:
                raise ValueError(f"Fichier inattendu : {path}")
            d = pd.read_csv(path, dtype={"horodatage": str})
            conn.executemany(
                "INSERT INTO releves (id_consommateur, horodatage, puissance_kw) VALUES (?,?,?)",
                zip([nom] * len(d), d["horodatage"], (d["puissance_w"] / 1000).astype(float)))
            if verifier:
                kwh = d["puissance_w"] * db.PAS_HEURES / 1000
                heure = d["horodatage"].str.slice(11, 13).astype(int)
                hp = (heure >= 6) & (heure < 22)
                tarif = np.where(hp, TARIFS[nom][0], TARIFS[nom][1]) / 100
                reference[nom] = dict(kWh=kwh.sum(), cout=(kwh * tarif).sum(), kWh_HC=kwh[~hp].sum())
            if afficher:
                print(f"  {nom:<16} {len(d):>7} relevés chargés  ({os.path.basename(path)})")
        conn.commit()
    finally:
        conn.close()
    os.replace(temporaire, db.DB_PATH)                 # la nouvelle base remplace l'ancienne d'un seul coup

    # 3) vérification : les requêtes SQL doivent redonner les résultats calculés directement avec pandas
    if verifier:
        synth = db.synthese_consommateurs().set_index("consommateur")
        assert len(synth) == len(reference) == len(TARIFS), "Consommateurs manquants"
        for nom, ref in reference.items():
            for col in ("kWh", "cout", "kWh_HC"):
                assert np.isclose(synth.loc[nom, col], ref[col], rtol=1e-6), f"Écart sur {nom} / {col}"
        if afficher:
            print("\nVérification OK : consommation, coût et heures creuses identiques entre SQL et pandas (10 consommateurs).")
    if afficher:
        print(f"Base créée : {db.DB_PATH}  ({time.time() - t0:.0f} s)")
    return db.DB_PATH


def main():
    construire_base(verifier=True, afficher=True)
    print(f"\nRequête 1 – Consommation totale : {db.consommation_totale_mwh():,.0f} MWh".replace(",", " "))
    print("\nRequête 2 – Consommation annuelle moyenne par consommateur, par type (MWh) :")
    print(db.consommation_moyenne_par_type().round(1).to_string(index=False))
    print("\nRequête 3 – Coût annuel moyen (k€) et pic de puissance (kW), par type :")
    print(db.cout_moyen_par_type().round(1).to_string(index=False))


if __name__ == "__main__":
    main()
