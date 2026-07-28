"""Page « Entraînement » : combien j'en fais, et est-ce bien réparti ?

Fusionne les anciennes pages Cardio et Renforcement — la question posée est la
même (« la charge est-elle raisonnable, et équilibrée entre groupes
musculaires ? ») et séparer les deux ne faisait que dupliquer le contexte.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import streamlit as st

import charts
import common
import queries
import theme
import ui
from health import stats
from health.metrics import require as metric

st.set_page_config(page_title=common.PAGE_TITLE.format("Entraînement"), layout="wide")
theme.inject_css()

st.title("Entraînement")
st.caption("Combien j'en fais, et est-ce bien réparti ?")

start, end = common.date_range_picker()
full_daily = queries.daily()  # le modèle CTL/ATL a besoin de tout l'historique
d = queries.daily(start, end)
weekly = queries.weekly()
sets_df = queries.strength_sets(start, end)
sessions = queries.strength_sessions(start, end)
workouts_df = queries.workouts(start, end)

if full_daily.empty:
    st.info("Pas encore de données ingérées.")
    st.stop()

# =============================================================================
# Modèle de forme
# =============================================================================
ctl_df = stats.ctl_atl_tsb(full_daily, load_col="cardio_load_total")
ctl_period = ctl_df[(ctl_df["local_date"] >= pd.Timestamp(start)) & (ctl_df["local_date"] <= pd.Timestamp(end))]
maturity = float(ctl_df.iloc[-1]["ctl_maturity"])
if maturity < 1.0:
    st.warning(
        f"Le CTL est une moyenne mobile {stats.CTL_DAYS} jours ; l'historique n'en compte que "
        f"{len(full_daily)} ({maturity:.0%} de maturité) — à lire comme indicatif, pas définitif.",
        icon="⚠️",
    )

with ui.card("Charge : fond, fatigue, fraîcheur"):
    c1, c2, c3 = st.columns(3)
    with c1:
        st.plotly_chart(charts.metric_chart(ctl_period, metric("ctl")), width="stretch")
    with c2:
        st.plotly_chart(charts.metric_chart(ctl_period, metric("atl")), width="stretch")
    with c3:
        st.plotly_chart(charts.metric_chart(ctl_period, metric("tsb")), width="stretch")

with ui.card("ACWR — charge aiguë (7j) / chronique (28j)", metric("acwr_ratio").how_read):
    fig = charts.metric_chart(d, metric("acwr_ratio"))
    st.plotly_chart(fig, width="stretch")

# =============================================================================
# Volume par groupe musculaire — deux unités
# =============================================================================
with ui.card(
    "Volume par groupe musculaire",
    "En minutes ET en nombre de séries : une partie des séances n'a aucun horodatage à la "
    "source (segment_start absent) et n'existe donc qu'en nombre de séries. Colonnes "
    "estimated_segments / segments_without_duration (mart.weekly) et duration_is_estimated "
    "(mart.strength_sets) tracent cette incertitude.",
):
    weekly_period = weekly[
        (pd.to_datetime(weekly["week_end"]) >= pd.Timestamp(start))
        & (pd.to_datetime(weekly["week_start"]) <= pd.Timestamp(end))
    ]
    n_estimated = int(sets_df["duration_is_estimated"].fillna(False).sum()) if "duration_is_estimated" in sets_df else 0
    n_no_duration = int(weekly_period["segments_without_duration"].sum()) if "segments_without_duration" in weekly_period else 0
    if not sets_df.empty:
        st.caption(
            f"Sur la période : {n_estimated}/{len(sets_df)} séries à durée reconstruite, "
            f"{n_no_duration} série(s) sans aucun horodatage sur les semaines concernées."
        )

    col_a, col_b = st.columns(2)
    with col_a:
        fig = charts.muscle_group_bar(weekly_period, "week_start", suffix="_min", y_title="minutes",
                                       title="Minutes sous tension / semaine")
        st.plotly_chart(fig, width="stretch")
    with col_b:
        fig = charts.muscle_group_bar(weekly_period, "week_start", suffix="_segments", y_title="séries",
                                       title="Séries / semaine")
        st.plotly_chart(fig, width="stretch")

# Comparatif semaine sur semaine et assiduité : venus de la page « Progression »,
# qui a été resserrée sur la seule condition cardio de fond. Ce sont des
# questions sur ce qu'on FAIT — donc d'ici.
with ui.card("Volume de renforcement : cette semaine vs la précédente"):
    if len(weekly) < 2:
        st.info("Pas assez de semaines complètes pour une comparaison semaine sur semaine.")
    else:
        wk = weekly.sort_values("week_start")
        this_week, last_week = wk.iloc[-1], wk.iloc[-2]
        groups = [g for g in charts.MUSCLE_GROUP_ORDER if f"{g}_min" in wk.columns]
        if groups:
            st.plotly_chart(
                charts.grouped_bars(
                    [charts.MUSCLE_GROUP_LABELS[g] for g in groups],
                    [
                        (f"Semaine du {pd.Timestamp(last_week['week_start']):%d/%m}",
                         [last_week.get(f"{g}_min", 0) for g in groups]),
                        (f"Semaine du {pd.Timestamp(this_week['week_start']):%d/%m}",
                         [this_week.get(f"{g}_min", 0) for g in groups]),
                    ],
                    y_title="minutes", height=320,
                ),
                width="stretch",
            )

        delta_cols = st.columns(4)
        delta_specs = [
            ("avg_steps_delta", "Pas / jour (Δ)", "{:+.0f}"),
            ("strength_sessions_delta", "Séances renfo (Δ)", "{:+.0f}"),
            ("avg_sleep_score_delta", "Score sommeil (Δ)", "{:+.0f}"),
            ("total_work_minutes_delta", "Sous tension (Δ min)", "{:+.0f}"),
        ]
        for col, (key, label, fmt) in zip(delta_cols, delta_specs):
            val = this_week.get(key)
            col.metric(label, fmt.format(val) if pd.notna(val) else "—")
        st.caption(
            f"{stats.confidence_label(len(weekly), unit='semaines')} — les colonnes *_delta de "
            "mart.weekly comparent chaque semaine à la précédente."
        )

with ui.card(
    "Assiduité",
    "Minutes d'activité par jour, disposées en grille semaine × jour : le motif "
    "hebdomadaire (quels jours décrochent) se voit d'un coup d'œil.",
):
    st.plotly_chart(
        charts.calendar_heatmap(d, "workout_minutes", title="Minutes d'activité (cardio + renfo)"),
        width="stretch",
    )

with ui.card("Équilibre musculaire (période sélectionnée)"):
    if not sets_df.empty:
        counts = sets_df["muscle_group"].value_counts().to_dict()
        fig = charts.radar(counts, title="Séries par groupe musculaire")
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("Aucune série de renforcement sur cette période.")

# =============================================================================
# Séances + mouvements délaissés
# =============================================================================
with ui.card("Séances de la période"):
    if not sessions.empty:
        tbl = sessions.sort_values("local_date", ascending=False)[
            ["local_date", "workout_name", "duration_min", "rpe", "work_segments", "distinct_movements"]
        ].rename(columns={
            "local_date": "Date", "workout_name": "Séance", "duration_min": "Durée (min)",
            "rpe": "RPE", "work_segments": "Séries", "distinct_movements": "Mouvements distincts",
        })
        st.dataframe(tbl, width="stretch", hide_index=True)
    else:
        st.info("Aucune séance de renforcement sur cette période.")

with ui.card("Mouvements délaissés"):
    # Correction du bug de l'ancienne page Renforcement : elle rechargeait tout
    # l'historique (`queries.strength_sets()`) sans jamais tenir compte de la
    # période sélectionnée à l'écran, qui n'avait donc aucun effet ici. On
    # retient l'historique complet (nécessaire pour connaître la dernière fois
    # qu'un mouvement a été pratiqué, y compris avant la période) mais borné à la
    # fin de la période choisie, pour que le contrôle de période garde un effet
    # visible et que « aujourd'hui » corresponde bien à `end`.
    all_sets = queries.strength_sets()
    if not all_sets.empty:
        all_sets = all_sets[pd.to_datetime(all_sets["local_date"]) <= pd.Timestamp(end)]
    if all_sets.empty:
        st.caption("Pas d'historique de renforcement.")
    else:
        last_seen = all_sets.groupby(["segment_name", "muscle_group"])["local_date"].max().reset_index()
        last_seen["jours_depuis"] = (pd.Timestamp(end) - pd.to_datetime(last_seen["local_date"])).dt.days
        stale = last_seen[last_seen["jours_depuis"] >= 14].sort_values("jours_depuis", ascending=False)
        if stale.empty:
            st.caption("Tous les mouvements pratiqués au moins une fois dans les 14 jours précédant la fin de période.")
        else:
            st.dataframe(
                stale.rename(columns={
                    "segment_name": "Mouvement", "muscle_group": "Groupe",
                    "local_date": "Dernière fois", "jours_depuis": "Jours écoulés",
                }),
                width="stretch", hide_index=True,
            )

# =============================================================================
# Détail d'une séance — mart.workouts n'était affichée nulle part
# =============================================================================
with ui.card("Séances cardio (mart.workouts) et détail intra-journalier"):
    if workouts_df.empty:
        st.info("Aucune séance cardio sur cette période.")
    else:
        display_cols = ["local_date", "activity_name", "workout_kind", "duration_min", "calories",
                         "avg_hr", "peak_hr", "distance_m"]
        st.dataframe(
            workouts_df[display_cols].rename(columns={
                "local_date": "Date", "activity_name": "Activité", "workout_kind": "Type",
                "duration_min": "Durée (min)", "calories": "Kcal", "avg_hr": "FC moy",
                "peak_hr": "FC pic", "distance_m": "Distance (m)",
            }),
            width="stretch", hide_index=True,
        )

        options = list(workouts_df.itertuples(index=False))
        labels = [f"{getattr(o, 'local_date')} — {getattr(o, 'activity_name')} ({getattr(o, 'duration_min'):.0f} min)"
                  for o in options]
        idx = st.selectbox("Séance à détailler", range(len(options)), format_func=lambda i: labels[i])
        chosen_date = str(getattr(options[idx], "local_date"))

        hr_df = queries.heart_rate_intraday(chosen_date)
        zones_df = queries.hr_zones(chosen_date)
        fig = charts.intraday_hr(hr_df, zones_df, title=f"Fréquence cardiaque — {chosen_date}")
        st.plotly_chart(fig, width="stretch")
