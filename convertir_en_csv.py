"""
convertir_en_csv.py : à lancer UNE SEULE FOIS, en local, pour transformer les relevés Excel en CSV.

Pourquoi : les CSV se lisent en quelques secondes (les Excel en plusieurs minutes et beaucoup de mémoire),
ce qui est indispensable pour que l'application redémarre vite sur Render.
Il faut pour cela le package openpyxl (pip install openpyxl) : inutile sur Render.

Usage :   python convertir_en_csv.py
Résultat : un fichier data/<Consommateur>.csv par consommateur (colonnes : horodatage, puissance_w).
"""
import glob
import os

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
SORTIE = os.path.join(BASE, "data")


def lire(path):
    d = pd.read_excel(path)
    d.columns = ["horodatage", "puissance_w"]
    if not pd.api.types.is_datetime64_any_dtype(d["horodatage"]):      # Agri_4 : dates en texte jj/mm/aaaa
        d["horodatage"] = pd.to_datetime(d["horodatage"], format="%d/%m/%Y %H:%M:%S")
    d["horodatage"] = d["horodatage"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return d


def main():
    fichiers = sorted(glob.glob(os.path.join(BASE, "**", "*.xlsx"), recursive=True))
    fichiers = [f for f in fichiers if os.path.basename(os.path.dirname(f)) != "data"]
    if not fichiers:
        raise FileNotFoundError("Aucun fichier .xlsx trouvé : lancez ce script à côté des dossiers Agriculteurs, Industriels, ...")
    os.makedirs(SORTIE, exist_ok=True)
    for path in fichiers:
        nom = os.path.basename(os.path.dirname(path))              # ex. "Agriculteur 1"
        d = lire(path)
        cible = os.path.join(SORTIE, nom.replace(" ", "_") + ".csv")
        d.to_csv(cible, index=False)
        print(f"{nom:<16} {len(d):>7} lignes -> {os.path.relpath(cible, BASE)}")
    print("\nTerminé. Les CSV sont dans le dossier data/ : ils seront versionnés sur GitHub.")


if __name__ == "__main__":
    main()
