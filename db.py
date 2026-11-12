"""
db.py : accès aux données (SQLite) pour le dashboard.

Règle du TP4 : aucune connexion n'est gardée ouverte. Chaque requête ouvre sa connexion
puis la ferme (voir `connexion()`).
"""
import os
import sqlite3
from contextlib import contextmanager

import pandas as pd

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "consommation.db")
PAS_HEURES = 5 / 60            # un relevé = 5 minutes -> énergie (kWh) = puissance (kW) x 5/60

# Tarif applicable à un relevé : même contrat que le consommateur ET heure du relevé dans la plage
# [heure_debut, heure_fin[. Une plage qui "passe minuit" (heure_debut > heure_fin, ex. HC 22h -> 6h)
# est gérée par le 2e cas.
#
# Pour rester rapide, on agrège d'abord les relevés par (consommateur, heure) : la jointure avec les
# tarifs se fait alors sur 24 lignes par consommateur au lieu de ~100 000.
_PAR_HEURE = """
    (SELECT id_consommateur,
            CAST(strftime('%H', horodatage) AS INTEGER) AS h,
            SUM(puissance_kw)                           AS somme_kw,
            MAX(puissance_kw)                           AS pic_kw
     FROM releves
     GROUP BY id_consommateur, h)
"""
_JOINTURE_TARIF = """
    JOIN consommateurs c ON c.id_consommateur = r.id_consommateur
    JOIN tarifs t        ON t.id_contrat = c.id_contrat
                        AND (
                              (t.heure_debut < t.heure_fin AND r.h >= t.heure_debut AND r.h < t.heure_fin)
                           OR (t.heure_debut > t.heure_fin AND (r.h >= t.heure_debut OR r.h < t.heure_fin))
                        )
"""


@contextmanager
def connexion():
    """Ouvre une connexion SQLite et la ferme toujours à la sortie."""
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Base introuvable ({DB_PATH}). Lancez d'abord : python init_db.py")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def requete(sql, params=()):
    """Exécute une requête SELECT et renvoie un DataFrame (connexion ouverte puis fermée)."""
    with connexion() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def _filtre_types(types):
    """Fragment SQL + paramètres pour filtrer sur une liste de types (None = tous)."""
    if types is None:
        return "", ()
    types = list(types)
    if not types:
        return "WHERE 0", ()
    return f"WHERE c.type IN ({','.join('?' * len(types))})", tuple(types)


# --------------------------------------------------------------------------- requêtes du dashboard
def synthese_consommateurs(types=None):
    """Une ligne par consommateur : consommation, facture, part en heures creuses, pic, position."""
    where, params = _filtre_types(types)
    sql = f"""
        SELECT c.id_consommateur                                  AS consommateur,
               c.type                                             AS type,
               c.latitude                                         AS lat,
               c.longitude                                        AS lon,
               SUM(r.somme_kw) * {PAS_HEURES}                     AS kWh,
               SUM(r.somme_kw * {PAS_HEURES} * t.prix_kwh)        AS cout,
               SUM(CASE WHEN t.plage = 'HC' THEN r.somme_kw * {PAS_HEURES} ELSE 0 END) AS kWh_HC,
               MAX(r.pic_kw)                                      AS pic_kw
        FROM {_PAR_HEURE} r
        {_JOINTURE_TARIF}
        {where}
        GROUP BY c.id_consommateur, c.type, c.latitude, c.longitude
        ORDER BY c.id_consommateur
    """
    return requete(sql, params)


def consommation_mensuelle(types=None):
    """Consommation (kWh) par mois et par type."""
    where, params = _filtre_types(types)
    sql = f"""
        SELECT CAST(strftime('%m', r.horodatage) AS INTEGER) AS mois,
               c.type                                         AS type,
               SUM(r.puissance_kw) * {PAS_HEURES}             AS kWh
        FROM releves r
        JOIN consommateurs c ON c.id_consommateur = r.id_consommateur
        {where}
        GROUP BY mois, c.type
        ORDER BY mois
    """
    return requete(sql, params)


# --------------------------------------------------------------------------- requêtes de vérification (résultats du TP1)
def consommation_totale_mwh():
    """TP1 Q1 : consommation totale sur la période (MWh)."""
    df = requete(f"SELECT SUM(puissance_kw) * {PAS_HEURES} / 1000 AS mwh FROM releves")
    return float(df["mwh"].iloc[0])


def consommation_moyenne_par_type():
    """TP1 Q4 : consommation annuelle moyenne par consommateur, pour chaque type (MWh)."""
    return requete(f"""
        SELECT type, AVG(mwh) AS conso_moyenne_mwh
        FROM (SELECT c.type AS type, c.id_consommateur AS id, SUM(r.puissance_kw) * {PAS_HEURES} / 1000 AS mwh
              FROM releves r JOIN consommateurs c ON c.id_consommateur = r.id_consommateur
              GROUP BY c.type, c.id_consommateur)
        GROUP BY type ORDER BY type
    """)


def cout_moyen_par_type():
    """TP1 Q7 : coût annuel moyen (k€) et pic de puissance (kW) par type."""
    return requete(f"""
        SELECT type, AVG(cout_eur) / 1000 AS cout_moyen_keur, MAX(pic_kw) AS pic_kw
        FROM (SELECT c.type AS type, c.id_consommateur AS id,
                     SUM(r.somme_kw * {PAS_HEURES} * t.prix_kwh) AS cout_eur, MAX(r.pic_kw) AS pic_kw
              FROM {_PAR_HEURE} r {_JOINTURE_TARIF}
              GROUP BY c.type, c.id_consommateur)
        GROUP BY type ORDER BY type
    """)
