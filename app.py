"""
TP5 – Dashboard Dash déployable sur Render.

- `server = app.server` est la variable exécutée par gunicorn (Start Command : gunicorn app:server).
- Au démarrage, la base SQLite est régénérée à partir des CSV du dossier data/ (voir init_db.py).
  Sur Render le disque est éphémère : la base n'existe jamais au démarrage, elle est donc recréée à chaque fois.

En local :
    pip install -r requirements.txt
    python app.py            # puis http://127.0.0.1:8050
"""
import os
import textwrap
from datetime import datetime
from functools import lru_cache

import folium
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, ctx, dcc, html
from folium.plugins import MarkerCluster

import db
import init_db

# ----------------------------------------------------------------------------
# 0. BASE DE DONNÉES : régénérée à partir des CSV au démarrage de l'application
# ----------------------------------------------------------------------------
# Le fichier .db n'est jamais versionné. Sur Render, elle est reconstruite à CHAQUE démarrage (disque éphémère).
# En local, on ne la reconstruit que si elle est absente
# (pour éviter d'attendre à chaque rechargement automatique) ; `python init_db.py` force la reconstruction.
if os.environ.get("RENDER") or not os.path.exists(db.DB_PATH):      # RENDER est définie automatiquement sur Render
    init_db.construire_base(verifier=False)

# ----------------------------------------------------------------------------
# 1. CONSTANTES (mêmes couleurs que TP1 et TP2)
# ----------------------------------------------------------------------------
TYPES = ["Agriculteur", "Industriel", "Site public"]
C = {"Agriculteur": "#2E8B57", "Industriel": "#1F4E79", "Site public": "#E08A00"}
MOIS = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]

def fr(x, n=0):
    """Format français : 2 408 ou 2 407,9"""
    return f"{x:,.{n}f}".replace(",", " ").replace(".", ",")


# ----------------------------------------------------------------------------
# 2. DONNÉES : tout passe par db.py (requêtes SQL sur la base SQLite)
# ----------------------------------------------------------------------------
def enrichir(df):
    """Colonnes dérivées, avec les mêmes noms qu'au TP3."""
    df = df.copy()
    df["conso_MWh"] = df["kWh"] / 1000
    df["prix_moy"] = df["cout"] / df["kWh"] * 100            # c€/kWh réellement payé
    df["pct_HC"] = df["kWh_HC"] / df["kWh"] * 100
    return df


def classer(df):
    """Tranche de facture (bornes fixes, calculées sur tous les consommateurs) et alerte sur le prix."""
    df = df.copy()
    df["tranche"] = pd.cut(df["cout"], bins=BORNES, labels=["Faible", "Moyenne", "Élevée"], include_lowest=True)
    df["alerte_prix"] = df["prix_moy"] > SEUIL_PRIX
    return df


@lru_cache(maxsize=16)
def synthese_filtree(types_key):
    """Requête SQL filtrée par type, mise en cache par combinaison de types."""
    return classer(enrichir(db.synthese_consommateurs(list(types_key))))


@lru_cache(maxsize=16)
def mensuel_filtre(types_key):
    """Requête SQL (consommation mensuelle) filtrée par type, mise en cache."""
    return db.consommation_mensuelle(list(types_key))


def charger():
    """Interroge la base pour tous les consommateurs : référence des échelles, bornes des tranches, seuil de prix."""
    global cons, BORNES, SEUIL_PRIX
    ref = enrichir(db.synthese_consommateurs())
    # Tranches : terciles calculés sur TOUS les consommateurs (stables quel que soit le filtre)
    BORNES = ref["cout"].quantile([0, 1 / 3, 2 / 3, 1]).values
    SEUIL_PRIX = 1.3 * ref["prix_moy"].median()
    cons = classer(ref)
    synthese_filtree.cache_clear()                 # les bornes ont pu changer : on vide les caches
    mensuel_filtre.cache_clear()


charger()
BORD = {"Faible": ("#BDBDBD", 2), "Moyenne": ("#757575", 3), "Élevée": ("#000000", 5)}

# ----------------------------------------------------------------------------
# 3. GRAPHIQUES (repris du TP1, filtrés par type)
# ----------------------------------------------------------------------------
def wrap(texte, largeur=44):
    """Titre sur plusieurs lignes pour tenir dans un petit panneau."""
    return "<br>".join(textwrap.wrap(texte, largeur))


def style(fig, titre):
    fig.update_layout(template="plotly_white", autosize=True, height=None, showlegend=False,
                      font=dict(size=11),
                      title=dict(text=wrap(titre), x=0.01, xanchor="left", y=0.97, yanchor="top", font=dict(size=12)),
                      margin=dict(t=58, l=48, r=14, b=38))
    return fig


def fig_vide(message):
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, font=dict(size=14, color="#777"))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return style(fig, "")


def fig_total(sub):                                          # TP1 – Q1 (texte simple)
    total = sub["conso_MWh"].sum()
    fig = go.Figure(go.Indicator(
        mode="number", value=total,
        number=dict(suffix=" MWh", valueformat=",.0f", font=dict(size=44, color="#1F4E79")),
        title=dict(text=f"{len(sub)} consommateur(s) sélectionné(s)", font=dict(size=12))))
    return style(fig, f"{fr(total)} MWh consommés sur la période")


def fig_moyenne(sub, types_sel):                             # TP1 – Q4 (barres)
    moy = sub.groupby("type")["conso_MWh"].mean().reindex(types_sel)
    if len(moy) > 1:
        ratio = moy.max() / moy.min()
        if ratio < 1.2:
            titre = f"Les types sélectionnés consomment à peu près autant par consommateur (~{fr(moy.mean())} MWh/an)"
        else:
            titre = (f"« {moy.idxmax()} » : {fr(moy.max())} MWh/an par consommateur, "
                     f"{ratio:.0f}× plus que « {moy.idxmin()} »")
    else:
        titre = f"« {moy.index[0]} » : {fr(moy.iloc[0])} MWh/an en moyenne par consommateur"
    fig = go.Figure(go.Bar(
        x=moy.index, y=moy.values, marker_color=[C[t] for t in moy.index],
        text=[f"{fr(v)} MWh" for v in moy.values], textposition="outside", cliponaxis=False))
    style(fig, titre)
    fig.update_layout(yaxis=dict(visible=False, range=[0, moy.max() * 1.25]), xaxis=dict(title=""))
    return fig


def fig_mensuel(types_sel):                                  # TP1 – Q5 (barres empilées)
    brut = mensuel_filtre(tuple(types_sel))                  # requête SQL (en cache) : kWh par mois et par type
    m = (brut.pivot_table(index="mois", columns="type", values="kWh", aggfunc="sum")
             .reindex(index=range(1, 13), columns=types_sel).fillna(0)) / 1000      # MWh
    tot = m.sum(axis=1)
    pic = int(tot.idxmax())
    fig = go.Figure()
    for t in types_sel:
        fig.add_trace(go.Bar(x=MOIS, y=m[t], name=t, marker_color=C[t],
                             hovertemplate="%{x} : %{y:,.0f} MWh<extra>" + t + "</extra>"))
    style(fig, f"Pic de consommation en {MOIS[pic - 1]} : {fr(tot.max())} MWh")
    fig.update_layout(barmode="stack", yaxis=dict(title="MWh"))
    return fig


def fig_nuage(sub):                                          # TP1 – Q6 (nuage de points)
    fig = go.Figure()
    for t in TYPES:
        s_ = sub[sub["type"] == t]
        if s_.empty:
            continue
        fig.add_trace(go.Scatter(
            x=s_["pct_HC"], y=s_["prix_moy"], mode="markers", name=t, text=s_["consommateur"],
            marker=dict(size=11, color=C[t], line=dict(width=1, color="white")),
            hovertemplate=("<b>%{text}</b><br>Part heures creuses : %{x:.1f} %"
                           "<br>Prix moyen : %{y:.1f} c€/kWh<extra></extra>")))
    if len(sub) >= 3:
        r = sub["pct_HC"].corr(sub["prix_moy"])
        if r <= -0.6:
            titre = f"Plus d'heures creuses = prix payé plus bas (corrélation {fr(r, 2)})"
        else:
            titre = f"Plus d'heures creuses ne suffit pas à payer moins cher (corrélation {fr(r, 2)})"
    else:
        titre = "Prix moyen payé selon la part d'heures creuses"
    style(fig, titre)
    fig.update_layout(
        xaxis=dict(title="Part en heures creuses (%)", range=[0, cons["pct_HC"].max() * 1.2]),
        yaxis=dict(title="Prix moyen (c€/kWh)", range=[0, cons["prix_moy"].max() * 1.2]))
    return fig


# ----------------------------------------------------------------------------
# 4. CARTE FOLIUM (reprise du TP2, filtrée par type) -> chaîne HTML pour html.Iframe
# ----------------------------------------------------------------------------
def popup_html(r):
    return f"""
    <div style="font-family:Arial; font-size:13px; min-width:210px">
      <div style="font-weight:bold; font-size:14px; color:{C[r.type]}">{r.consommateur}</div>
      <table style="width:100%; border-collapse:collapse; margin-top:4px">
        <tr><td>Type</td><td style="text-align:right"><b>{r.type}</b></td></tr>
        <tr><td>Consommation annuelle</td><td style="text-align:right"><b>{fr(r.conso_MWh)} MWh</b></td></tr>
        <tr><td>Facture annuelle</td><td style="text-align:right"><b>{fr(r.cout)} €</b></td></tr>
        <tr><td>Prix moyen</td><td style="text-align:right">{fr(r.prix_moy, 1)} c€/kWh</td></tr>
        <tr><td>Part en heures creuses</td><td style="text-align:right">{fr(r.pct_HC, 0)} %</td></tr>
        <tr><td>Tranche de facture</td><td style="text-align:right">{r.tranche}</td></tr>
      </table>
    </div>"""


def marqueur(r):
    couleur_bord, epaisseur = BORD[r.tranche]
    return folium.CircleMarker(
        location=[r.lat, r.lon],
        radius=6 + 14 * np.sqrt(r.conso_MWh / cons["conso_MWh"].max()),
        color=couleur_bord, weight=epaisseur, fill=True, fill_color=C[r.type], fill_opacity=0.85,
        tooltip=f"{r.consommateur} – {fr(r.conso_MWh)} MWh – {fr(r.cout)} €",
        popup=folium.Popup(popup_html(r), max_width=300))


def ajouter_groupe(m, nom, sous_ensemble, actif=True):
    fg = folium.FeatureGroup(name=nom, show=actif)
    cluster = MarkerCluster().add_to(fg)
    for r in sous_ensemble.itertuples():
        marqueur(r).add_to(cluster)
    fg.add_to(m)


def legende_html():
    types = "".join(f'<div><span style="display:inline-block;width:12px;height:12px;border-radius:50%;'
                    f'background:{C[t]};margin-right:6px"></span>{t}</div>' for t in TYPES)
    tranches = "".join(
        f'<div><span style="display:inline-block;width:12px;height:12px;border-radius:50%;'
        f'border:{BORD[k][1]}px solid {BORD[k][0]};margin-right:6px;box-sizing:border-box"></span>'
        f'Facture {k.lower()} ({fr(BORNES[i] / 1000)}–{fr(BORNES[i + 1] / 1000)} k€)</div>'
        for i, k in enumerate(["Faible", "Moyenne", "Élevée"]))
    return f"""
    <div style="position:fixed; bottom:14px; left:10px; z-index:9999; background:white; padding:6px 10px;
                border:1px solid #999; border-radius:6px; font-family:Arial; font-size:11px;
                box-shadow:0 1px 4px rgba(0,0,0,.3)">
      <b>Lecture de la carte</b>
      <div style="margin-top:6px"><i>Couleur = type de consommateur</i></div>{types}
      <div style="margin-top:6px"><i>Contour = tranche de facture annuelle</i></div>{tranches}
      <div style="margin-top:6px"><i>Taille = consommation annuelle</i></div>
      <div style="margin-top:6px;color:#C0392B"><b>Positions supposées</b> (non fournies)</div>
    </div>"""


def carte_html(sub, types_sel):
    m = folium.Map(location=[cons["lat"].mean(), cons["lon"].mean()], zoom_start=9, tiles=None, control_scale=True)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri", name="Fond clair (Esri)", max_zoom=16).add_to(m)
    m.fit_bounds([[sub["lat"].min(), sub["lon"].min()], [sub["lat"].max(), sub["lon"].max()]], padding=(40, 40))
    for t in types_sel:
        ajouter_groupe(m, f"Type : {t}", sub[sub["type"] == t])
    for tr in ["Faible", "Moyenne", "Élevée"]:
        ajouter_groupe(m, f"Facture {tr.lower()}", sub[sub["tranche"] == tr], actif=False)
    ajouter_groupe(m, "⚠ Prix au kWh élevé (> 1,3 × médiane)", sub[sub["alerte_prix"]], actif=False)
    folium.LayerControl(collapsed=True).add_to(m)
    m.get_root().html.add_child(folium.Element(legende_html()))
    return m.get_root().render()


CARTE_VIDE = ("<html><body style='font-family:Arial;color:#777;display:flex;align-items:center;"
              "justify-content:center;height:100%'><p>Sélectionnez au moins un type de consommateur.</p></body></html>")

# ----------------------------------------------------------------------------
# 5. LAYOUT : une seule page, sans défilement (tout tient dans la fenêtre)
# ----------------------------------------------------------------------------
app = Dash(__name__)
app.title = "Dashboard consommation électrique"
server = app.server        # exposé pour gunicorn : gunicorn app:server
app.index_string = """<!DOCTYPE html>
<html>
<head>
{%metas%}
<title>{%title%}</title>
{%favicon%}
{%css%}
<style>html, body {margin: 0; height: 100%; overflow: hidden;}</style>
</head>
<body>
{%app_entry%}
<footer>
{%config%}
{%scripts%}
{%renderer%}
</footer>
</body>
</html>"""

PANNEAU = {"position": "relative", "backgroundColor": "white", "border": "1px solid #E0E0E0",
           "borderRadius": "8px", "minHeight": 0, "minWidth": 0, "overflow": "hidden"}
REMPLIR = {"position": "absolute", "top": 0, "left": 0, "right": 0, "bottom": 0}   # le contenu remplit son panneau
CONFIG = {"displayModeBar": False, "responsive": True}

LEGENDE_COULEURS = html.Div(
    style={"display": "flex", "gap": "14px", "alignItems": "center", "fontSize": "13px"},
    children=[html.Span([html.Span(style={"display": "inline-block", "width": "11px", "height": "11px",
                                          "borderRadius": "50%", "backgroundColor": C[t], "marginRight": "5px"}), t])
              for t in TYPES])

app.layout = html.Div(
    style={"height": "100vh", "boxSizing": "border-box", "display": "flex", "flexDirection": "column",
           "gap": "8px", "padding": "8px 12px", "fontFamily": "Arial, sans-serif",
           "backgroundColor": "#F5F6F8", "overflow": "hidden"},
    children=[
        # Bandeau : titre + filtre transversal
        html.Div(
            style={"display": "flex", "alignItems": "center", "justifyContent": "space-between",
                   "gap": "16px", "flex": "0 0 auto", "position": "relative", "zIndex": 10},
            children=[
                html.Div([
                    html.H1("Consommation électrique : usages, factures et localisation",
                            style={"margin": 0, "fontSize": "20px", "color": "#1F4E79"}),
                    html.Div("Un seul filtre pilote tous les graphiques et la carte",
                             style={"fontSize": "12px", "color": "#666"}),
                    dcc.Loading(type="circle", children=html.Div(id="statut", style={"fontSize": "11px", "color": "#888"})),
                ]),
                html.Div(
                    style={"display": "flex", "alignItems": "center", "gap": "14px"},
                    children=[
                        html.Button(
                            "↻ Actualiser les données", id="btn-actualiser", n_clicks=0,
                            title="Interroge de nouveau la base de données et met à jour tous les graphiques et la carte",
                            style={"backgroundColor": "#1F4E79", "color": "white", "border": "none", "borderRadius": "6px",
                                   "padding": "7px 14px", "fontSize": "13px", "fontWeight": "bold", "cursor": "pointer"}),
                        LEGENDE_COULEURS,
                        html.Label("Type de consommateur :", style={"fontWeight": "bold", "fontSize": "13px"}),
                        html.Div(style={"width": "340px"}, children=dcc.Dropdown(
                            id="filtre-type",
                            options=[{"label": t, "value": t} for t in TYPES],
                            value=TYPES, multi=True, placeholder="Choisissez un ou plusieurs types…")),
                    ]),
            ]),

        # Corps : graphiques (grille 2 x 2, TP1) à gauche, carte (TP2) à droite
        html.Div(
            style={"flex": "1 1 0", "minHeight": 0, "display": "grid", "gap": "8px",
                   "gridTemplateColumns": "minmax(0, 1.1fr) minmax(0, 1fr)", "gridTemplateRows": "minmax(0, 1fr)"},
            children=[
                html.Div(
                    style={"display": "grid", "gap": "8px", "minHeight": 0, "minWidth": 0,
                           "gridTemplateColumns": "minmax(0, 1fr) minmax(0, 1fr)",
                           "gridTemplateRows": "minmax(0, 1fr) minmax(0, 1fr)"},
                    children=[
                        html.Div(style=PANNEAU, children=dcc.Graph(id="g-total", style=REMPLIR, config=CONFIG)),
                        html.Div(style=PANNEAU, children=dcc.Graph(id="g-moyenne", style=REMPLIR, config=CONFIG)),
                        html.Div(style=PANNEAU, children=dcc.Graph(id="g-mensuel", style=REMPLIR, config=CONFIG)),
                        html.Div(style=PANNEAU, children=dcc.Graph(id="g-nuage", style=REMPLIR, config=CONFIG)),
                    ]),
                html.Div(style=PANNEAU, children=html.Iframe(
                    id="carte", srcDoc=carte_html(cons, TYPES), style={**REMPLIR, "width": "100%", "height": "100%", "border": "none"})),
            ]),
    ])

# ----------------------------------------------------------------------------
# 6. CALLBACK : un filtre -> 4 graphiques + la carte
# ----------------------------------------------------------------------------
@app.callback(
    Output("g-total", "figure"),
    Output("g-moyenne", "figure"),
    Output("g-mensuel", "figure"),
    Output("g-nuage", "figure"),
    Output("carte", "srcDoc"),
    Output("statut", "children"),
    Input("filtre-type", "value"),
    Input("btn-actualiser", "n_clicks"),
)
def mettre_a_jour(types_choisis, n_clicks):
    if ctx.triggered_id == "btn-actualiser":          # clic sur le bouton : on relit la base (bornes des tranches comprises)
        charger()
    statut = f"Données lues dans la base SQLite à {datetime.now():%H:%M:%S}"

    types_sel = [t for t in TYPES if t in (types_choisis or [])]
    if not types_sel:
        vide = fig_vide("Sélectionnez au moins un type de consommateur")
        return vide, vide, vide, vide, CARTE_VIDE, statut
    sub = synthese_filtree(tuple(types_sel))                  # requête SQL filtrée par type (en cache)
    return (fig_total(sub), fig_moyenne(sub, types_sel), fig_mensuel(types_sel),
            fig_nuage(sub), carte_html(sub, types_sel), statut)


if __name__ == "__main__":
    app.run(debug=True)
