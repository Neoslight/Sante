"""Page « Dépense » : où part mon énergie ?

Pas de bilan calorique ici : les journaux nutrition sont trop lacunaires côté
export pour calculer un déficit fiable. La page répond à une question plus
modeste mais vérifiable — dépense vs métabolisme de base, répartition par
filière (aérobie/glycolytique), sédentarité, et pas vs objectif RÉEL.
"""
import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import plotly.graph_objects as go
import streamlit as st

import charts
import common
import queries
import theme
import ui
from health.metrics import require as metric

st.set_page_config(page_title=common.PAGE_TITLE.format("Dépense"), layout="wide")
theme.inject_css()

st.title("Dépense")
st.caption("Où part mon énergie ?")
st.caption(
    "Les journaux nutrition sont trop lacunaires côté export pour calculer un déficit fiable : "
    "cette page montre la dépense et la sédentarité, jamais un solde calorique inventé."
)

start, end = common.date_range_picker()
d = queries.daily(start, end)
bmr = queries.bmr_kcal()

with ui.card("Dépense calorique vs métabolisme de base"):
    t = theme.active_tokens()

    def _add_bmr(fig):
        """Repère de métabolisme de base, posé sur la figure via le point
        d'accroche de `metric_block` : la page n'a pas à toucher au rendu."""
        fig.add_hline(y=bmr, line_dash="dot", line_color=t["ink_muted"],
                      annotation_text=f"BMR ≈ {bmr:.0f} kcal (Mifflin-St Jeor)",
                      annotation_font_color=t["ink_muted"])

    charts.metric_block(d, metric("calories_total"), show_trend=True, decorate=_add_bmr)
    st.caption(
        "BMR calculé à partir de ton profil réel (poids, taille, âge, sexe) — cf. queries.bmr_kcal. "
        "L'écart entre la courbe et la ligne pointillée est ce que l'activité a ajouté au repos strict."
    )

with ui.card(
    "Calories par zone de fréquence cardiaque",
    "Repos et léger sollicitent surtout la filière aérobie (lipides) ; modérée mélange les deux ; "
    "vigoureuse et pic font basculer vers la filière glycolytique (glucides), plus intense mais "
    "moins soutenable dans la durée.",
):
    zone_cols = [
        ("kcal_zone_rest", "Repos", 0), ("kcal_zone_light", "Légère", 2),
        ("kcal_zone_moderate", "Modérée", 3), ("kcal_zone_vigorous", "Vigoureuse", 1),
        ("kcal_zone_peak", "Pic", 7),
    ]
    if d[[c for c, _, _ in zone_cols]].dropna(how="all").empty:
        st.info("Pas de calories par zone sur cette période.")
    else:
        fig = go.Figure()
        for col, label, palette_idx in zone_cols:
            if col in d.columns:
                fig.add_trace(go.Bar(x=d["local_date"], y=d[col], name=label,
                                      marker_color=t["categorical"][palette_idx], marker_line_width=0))
        layout = charts.base_layout(y_title="kcal", height=340)
        layout["barmode"] = "stack"
        fig.update_layout(**layout)
        st.plotly_chart(fig, width="stretch")

col_a, col_b = st.columns(2)
with col_a:
    with ui.card("Sédentarité"):
        charts.metric_block(d, metric("sedentary_min"))
with col_b:
    with ui.card("Plus longue période assise"):
        charts.metric_block(d, metric("longest_sedentary_period_min"))

with ui.card("Pas vs objectif réel"):
    steps_metric = metric("steps")
    real_goal = queries.steps_goal()
    if real_goal is not None:
        # Le registre porte un objectif par défaut (10 000, valeur générique) pour
        # les pages qui n'ont pas accès à mart.goals. Ici on connaît le VRAI
        # objectif Fitbit : on le substitue plutôt que d'afficher un chiffre
        # d'exemple à la place d'une donnée réelle.
        steps_metric = dataclasses.replace(steps_metric, target=real_goal)
    charts.metric_block(d, steps_metric, show_trend=True)
    if real_goal is not None:
        st.caption(f"Objectif quotidien Fitbit actuel : {real_goal:,.0f} pas.".replace(",", " "))
    else:
        st.caption("Aucun objectif de pas trouvé dans mart.goals.")
