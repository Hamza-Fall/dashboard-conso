# Dashboard consommation électrique (Dash + SQLite)

Dashboard Dash alimenté par une base SQLite **régénérée à chaque démarrage** à partir des CSV du dossier `data/`.

## Lancer en local
```
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows (PowerShell)
pip install -r requirements.txt
python app.py                     # puis http://127.0.0.1:8050
```
`python init_db.py` recrée la base et vérifie le chargement (requêtes de contrôle).

## Données
Les relevés (un CSV par consommateur, toutes les 5 minutes) sont dans `data/`. Ils proviennent des fichiers Excel
d'origine, convertis une fois par `python convertir_en_csv.py`. Les positions GPS sont supposées (Île-de-France).

## Déploiement sur Render
- Build Command : `pip install -r requirements.txt`
- Start Command : `gunicorn app:server --timeout 300`
- La base `.db` n'est jamais versionnée : elle est reconstruite au démarrage (disque éphémère).

## Structure
- `app.py` : dashboard (expose `server = app.server` pour gunicorn)
- `db.py` : accès aux données, une connexion ouverte puis fermée à chaque requête
- `init_db.py` : création du schéma (3 tables) et chargement des CSV
- `convertir_en_csv.py` : conversion unique des Excel en CSV
