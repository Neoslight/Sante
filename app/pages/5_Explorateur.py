"""Page « Explorateur » : qu'est-ce qui influence quoi ?

Remplace l'ancienne matrice de corrélation brute (un `df.corr()` sans p-value
ni correction) par `health.stats.corr_table` : r, n et une correction de
Benjamini-Hochberg. Sur un historique de 39 jours, croiser une poignée de
métriques revient déjà à multiplier les tests — sans correction, une partie
des "corrélations" affichées serait due au hasard.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import charts
import common
import queries
import theme
import ui
import health.metrics as metrics
from health import stats

st.set_page_config(page_title=common.PAGE_TITLE.format("Explorateur"), layout="wide")
theme.inject_css()

st.title("Explorateur")
st.caption("Qu'est-ce qui influence quoi ?")

start, end = common.date_range_picker()
d = queries.daily(start, end)

available_keys = metrics.keys_in(d.columns)
default_keys = [k for k in metrics.EXPLORER_DEFAULT if k in available_keys] or available_keys[:3]


def _label(key: str) -> str:
    m = metrics.get(key)
    return m.label if m else key


# =============================================================================
# Filtres — tous les contrôles de la page regroupés en un seul endroit, avant
# les résultats qu'ils pilotent (métriques libres, corrélations, décalage
# temporel). Le décalage à représenter a besoin de connaître la cause, l'effet
# et le décalage maximum choisis ici pour calculer sa valeur par défaut
# (le décalage le plus corrélé) : lag_table est donc calculée dans cette carte
# et réutilisée telle quelle plus bas, sans être recalculée.
# =============================================================================
with ui.card("Filtres"):
    granularity = st.radio("Granularité", ["Jour", "Semaine"], horizontal=True)
    selected = st.multiselect("Métriques", available_keys, default=default_keys, format_func=_label)
    corr_cols = st.multiselect("Métriques à corréler", available_keys, default=default_keys,
                                format_func=_label, key="corr")

    c1, c2, c3 = st.columns(3)
    cause = c1.selectbox("Cause (jour J)", available_keys, index=available_keys.index("cardio_load_total")
                          if "cardio_load_total" in available_keys else 0, format_func=_label)
    effect = c2.selectbox("Effet (jour J + décalage)", available_keys,
                           index=available_keys.index("readiness_score") if "readiness_score" in available_keys else 0,
                           format_func=_label)
    max_lag = c3.slider("Décalage maximum (jours)", 0, 7, 3)

    lag_table = stats.lagged_correlation(d, cause, effect, lags=range(0, max_lag + 1))
    valid_lags = lag_table.dropna(subset=["r"])
    default_lag = int(valid_lags.loc[valid_lags["r"].abs().idxmax(), "lag_days"]) if not valid_lags.empty else 0
    lag_choice = st.slider("Décalage à représenter", 0, max_lag, min(default_lag, max_lag), key="lag_scatter")

# =============================================================================
# Métriques libres
# =============================================================================
with ui.card("Métriques libres"):
    plot_df = d.copy()
    plot_df["local_date"] = pd.to_datetime(plot_df["local_date"])
    if granularity == "Semaine" and selected:
        plot_df = plot_df.set_index("local_date")[selected].resample("W-MON").mean().reset_index()

    cols = st.columns(2)
    for i, key in enumerate(selected):
        m = metrics.get(key)
        with cols[i % 2]:
            fig = charts.metric_chart(plot_df, m, show_trend=True)
            st.plotly_chart(fig, width="stretch")

# =============================================================================
# Corrélations honnêtes
# =============================================================================
with ui.card("Corrélations"):
    n_pairs = len(corr_cols) * (len(corr_cols) - 1) // 2
    if n_pairs:
        expected_false = 0.05 * n_pairs
        st.caption(
            f"{len(corr_cols)} métriques croisées = {n_pairs} tests. Sans correction, on attendrait "
            f"environ {expected_false:.1f} corrélation(s) « significative(s) à 5 % » par pur hasard. "
            "La matrice ci-dessous grise donc toute paire non significative après correction de "
            "Benjamini-Hochberg : seules les cases en couleur méritent d'être lues."
        )
    if n_pairs >= 1:
        table = stats.corr_table(d, corr_cols)
        labels = {c: _label(c) for c in corr_cols}
        fig = charts.correlation_heatmap(table, labels=labels)
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("Choisis au moins deux métriques pour une matrice de corrélation.")

# =============================================================================
# Corrélation décalée dans le temps
# =============================================================================
with ui.card(
    "Effet décalé dans le temps",
    "Généralise le croisement « charge de la veille → readiness du lendemain » : à quel "
    "décalage (en jours) l'effet d'une métrique sur une autre est-il le plus marqué, s'il existe.",
):
    st.dataframe(
        lag_table.rename(columns={"lag_days": "Décalage (j)", "r": "r", "n": "n",
                                   "p_value": "p", "is_significant": "Significatif (corrigé)"}),
        width="stretch", hide_index=True,
    )

    pair = pd.DataFrame({"cause": d[cause], "effect": d[effect].shift(-lag_choice)}).dropna()
    if pair.empty:
        st.info("Pas assez de points pour ce décalage sur cette période.")
    else:
        t = theme.active_tokens()
        fig = go.Figure(go.Scatter(
            x=pair["cause"], y=pair["effect"], mode="markers",
            marker=dict(color=t["categorical"][0], size=9, line=dict(width=1, color=t["surface"])),
        ))
        fig.update_layout(**charts.base_layout(y_title=f"{_label(effect)} (J+{lag_choice})", height=340))
        fig.update_xaxes(title=f"{_label(cause)} (jour J)")
        st.plotly_chart(fig, width="stretch")
        st.caption(stats.confidence_label(len(pair)))

# =============================================================================
# Console SQL
# =============================================================================
with ui.card(
    "Console SQL (lecture seule)",
    "Tables disponibles : raw.* (bruts) et mart.daily / mart.sleep / mart.workouts / "
    "mart.strength_sessions / mart.strength_sets / mart.weekly / mart.hr_zones / "
    "mart.goals / mart.hrv_intraday / mart.spo2_intraday.",
):
    default_sql = "SELECT * FROM mart.daily ORDER BY local_date DESC LIMIT 20"
    sql = st.text_area("Requête", value=default_sql, height=100)
    if st.button("Exécuter"):
        try:
            result = queries.get_connection().execute(sql).df()
            st.dataframe(result, width="stretch")
        except Exception as e:
            st.error(str(e))
