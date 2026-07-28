"""Page « Récupération » : est-ce que je récupère ?

Regroupe tout ce qui se passe pendant et après la nuit : stades de sommeil,
dette cumulée, régularité du coucher, HRV et SpO2 nocturnes, température
cutanée, et la décomposition du score de readiness Fitbit en ses trois
sous-scores.
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
from health import stats
from health.metrics import require as metric

st.set_page_config(page_title=common.PAGE_TITLE.format("Récupération"), layout="wide")
theme.inject_css()

st.title("Récupération")
st.caption("Est-ce que je récupère ?")

start, end = common.date_range_picker()
full_daily = queries.daily()  # la dette de sommeil est un cumul glissant 14j : a besoin de lookback
d = queries.daily(start, end)
sl = queries.sleep(start, end)


def _clock_label(minutes_since_18h: float | None) -> str:
    """`sleep_midpoint_minutes` (et, ici, l'heure de coucher) sont ancrés à
    18h -- 0 = 18h, 360 = minuit, 540 = 3h -- justement pour éviter le saut de
    1440 minutes qu'un ancrage à minuit provoquerait dès qu'un coucher passe
    après 0h. On reconvertit en heure lisible pour l'affichage : personne ne
    lit "360 minutes" comme "minuit" du premier coup d'œil."""
    if minutes_since_18h is None or pd.isna(minutes_since_18h):
        return "—"
    total = int(round(minutes_since_18h)) % (24 * 60)
    total = (18 * 60 + total) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


# =============================================================================
# Stades de sommeil + dette cumulée
# =============================================================================
col_a, col_b = st.columns(2)
with col_a:
    with ui.card("Stades de sommeil"):
        if sl.empty or sl[["deep_minutes", "rem_minutes", "light_minutes", "awake_stage_minutes"]].dropna(how="all").empty:
            st.info("Pas de nuit enregistrée sur cette période.")
        else:
            t = theme.active_tokens()
            stages = [("deep_minutes", "Profond", t["categorical"][6]), ("rem_minutes", "REM", t["categorical"][0]),
                       ("light_minutes", "Léger", t["categorical"][2]), ("awake_stage_minutes", "Éveil", t["ink_muted"])]
            fig = go.Figure()
            for col, label, color in stages:
                if col in sl.columns:
                    fig.add_trace(go.Bar(x=sl["local_date"], y=sl[col], name=label, marker_color=color, marker_line_width=0))
            layout = charts.base_layout(y_title="minutes", height=340)
            layout["barmode"] = "stack"
            fig.update_layout(**layout)
            st.plotly_chart(fig, width="stretch")

with col_b:
    with ui.card("Dette de sommeil cumulée (14 j)"):
        debt_df = stats.sleep_debt(full_daily)
        debt_period = debt_df[(debt_df["local_date"] >= pd.Timestamp(start)) & (debt_df["local_date"] <= pd.Timestamp(end))]
        if debt_period["debt"].dropna().empty:
            st.info("Pas assez de données pour calculer une dette de sommeil.")
        else:
            t = theme.active_tokens()
            fig = go.Figure(go.Scatter(x=debt_period["local_date"], y=debt_period["debt"], mode="lines",
                                        line=dict(color=t["categorical"][7], width=2), fill="tozeroy",
                                        fillcolor=charts._with_opacity(t["categorical"][7], 0.12)))
            fig.add_hline(y=0, line_dash="dot", line_color=t["ink_muted"])
            fig.update_layout(**charts.base_layout(y_title="minutes de déficit cumulé", height=340))
            st.plotly_chart(fig, width="stretch")
            st.caption(
                "Positif = déficit accumulé vs objectif de sommeil réel (sleep_goal_minutes Fitbit). "
                "Se résorbe par la régularité, pas par une seule grasse matinée."
            )

# =============================================================================
# Régularité du coucher
# =============================================================================
with ui.card("Régularité du coucher"):
    if sl.empty or "sleep_start_local" not in sl.columns or sl["sleep_start_local"].dropna().empty:
        st.info("Pas d'horodatage de coucher sur cette période.")
    else:
        reg = sl[["local_date", "sleep_start_local"]].dropna().copy()
        reg["local_date"] = pd.to_datetime(reg["local_date"])
        start_dt = pd.to_datetime(reg["sleep_start_local"])
        minutes_of_day = start_dt.dt.hour * 60 + start_dt.dt.minute
        reg["anchored_min"] = (minutes_of_day - 18 * 60) % (24 * 60)
        reg = reg.sort_values("local_date")

        median_bedtime = reg["anchored_min"].median()
        c1, c2 = st.columns(2)
        c1.metric("Heure de coucher médiane", _clock_label(median_bedtime))
        reg["stddev_7j"] = reg.set_index("local_date")["anchored_min"].rolling("7D", min_periods=3).std().to_numpy()
        last_std = reg["stddev_7j"].dropna()
        c2.metric("Écart-type du coucher (7j)", f"{last_std.iloc[-1]:.0f} min" if not last_std.empty else "—")

        t = theme.active_tokens()
        fig = go.Figure(go.Scatter(x=reg["local_date"], y=reg["stddev_7j"], mode="lines",
                                    line=dict(color=t["categorical"][4], width=2)))
        fig.update_layout(**charts.base_layout(y_title="minutes (écart-type glissant 7j)", height=300))
        st.plotly_chart(fig, width="stretch")
        st.caption(
            f"{stats.confidence_label(len(reg))} — un coucher décalé chaque soir (écart-type élevé) "
            "est associé à une moins bonne récupération, indépendamment de la durée de sommeil."
        )

# =============================================================================
# HRV et SpO2 nocturnes, température
# =============================================================================
with ui.card("HRV et SpO2 nocturnes"):
    col_c, col_d = st.columns(2)
    with col_c:
        hrv_id = queries.hrv_intraday(start, end)
        if hrv_id.empty or hrv_id["rmssd_ms"].dropna().empty:
            st.info("Pas de mesure HRV intra-journalière sur cette période.")
        else:
            t = theme.active_tokens()
            fig = go.Figure(go.Scatter(x=hrv_id["timestamp_local"], y=hrv_id["rmssd_ms"], mode="lines",
                                        line=dict(color=t["categorical"][6], width=1)))
            fig.update_layout(**charts.base_layout("HRV nocturne (RMSSD)", "ms", 300))
            st.plotly_chart(fig, width="stretch")
    with col_d:
        charts.metric_block(d, metric("spo2_avg"), height=300)

    charts.metric_block(d, metric("skin_temp_deviation_c"))

# =============================================================================
# Disponibilité décomposée
# =============================================================================
with ui.card(
    "Disponibilité décomposée",
    "Sous-scores propriétaires Fitbit (non reproductibles) qui composent la disponibilité du jour.",
):
    sub_cols = ["readiness_score", "sleep_readiness", "hrv_readiness", "rhr_readiness"]
    if d[sub_cols].dropna(how="all").empty:
        st.info("Pas de disponibilité sur cette période.")
    else:
        t = theme.active_tokens()
        labels = {"readiness_score": "Disponibilité totale", "sleep_readiness": "Sommeil",
                  "hrv_readiness": "HRV", "rhr_readiness": "FC repos"}
        fig = go.Figure()
        for i, col in enumerate(sub_cols):
            if col in d.columns:
                width = 3 if col == "readiness_score" else 1.5
                fig.add_trace(go.Scatter(x=d["local_date"], y=d[col], mode="lines", name=labels[col],
                                          line=dict(color=t["categorical"][i], width=width)))
        fig.update_layout(**charts.base_layout(y_title="score", height=340))
        st.plotly_chart(fig, width="stretch")

# =============================================================================
# Siestes vs nuits
# =============================================================================
with ui.card("Siestes"):
    nap = d["sleep_nap_minutes"].dropna() if "sleep_nap_minutes" in d.columns else pd.Series(dtype=float)
    if nap.empty or (nap == 0).all():
        st.caption("Aucune sieste enregistrée sur cette période — le sommeil affiché est celui des nuits uniquement.")
    else:
        total_nap = nap.sum()
        st.metric("Minutes de sieste (période)", f"{total_nap:.0f} min")
        st.caption("Comptées à part de sleep_minutes_asleep, pour ne pas masquer une nuit courte "
                   "derrière une sieste compensatoire.")
