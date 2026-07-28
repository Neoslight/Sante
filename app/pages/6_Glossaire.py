"""Page « Glossaire » : ça veut dire quoi ?

Entièrement générée depuis `health.metrics` (aucune métrique décrite ici n'est
recopiée à la main) : pour chaque métrique du registre, ce que ça mesure,
comment la lire, d'où ça vient, et TA baseline actuelle calculée depuis les
vraies données (`health.stats.rolling_baseline`) plutôt qu'une valeur
générique. C'est la réponse directe à « pour que ça puisse être décrypté ».
"""
import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

import common
import queries
import theme
import health.metrics as metrics
from health import stats

st.set_page_config(page_title=common.PAGE_TITLE.format("Glossaire"), layout="wide")
theme.inject_css()

st.title("Glossaire")
st.caption("Ça veut dire quoi ?")
st.caption(
    "Chaque métrique du dashboard vient d'ici : health/metrics.py. Ajouter un graphe = ajouter "
    "une entrée dans ce registre, jamais recopier un titre ou une couleur à la main."
)

# La baseline se calcule sur TOUT l'historique disponible, indépendamment du
# sélecteur de période -- une baseline personnelle n'a de sens que sur le plus
# long recul possible.
common.date_range_picker()
full_daily = queries.daily()
weekly = queries.weekly()
ctl_df = stats.ctl_atl_tsb(full_daily) if not full_daily.empty else None
debt_df = stats.sleep_debt(full_daily) if not full_daily.empty else None
real_steps_goal = queries.steps_goal()


def _current_baseline(m: metrics.Metric) -> float | None:
    """Dernière valeur de `stats.rolling_baseline` pour cette métrique, depuis
    la source qui la porte réellement (mart.daily, mart.weekly, ou l'un des
    calculs dérivés CTL/ATL/TSB et dette de sommeil)."""
    if m.key in ("ctl", "atl", "tsb") and ctl_df is not None:
        df, col, date_col, window = ctl_df, m.key, "local_date", 28
    elif m.key == "sleep_debt" and debt_df is not None:
        df, col, date_col, window = debt_df, "debt", "local_date", 28
    elif m.key in weekly.columns:
        df, col, date_col, window = weekly, m.key, "week_start", 90
    elif m.key in full_daily.columns:
        df, col, date_col, window = full_daily, m.key, "local_date", 28
    else:
        return None
    valid = df[[date_col, col]].dropna()
    if len(valid) < 3:
        return None
    base = stats.rolling_baseline(df, col, date_col=date_col, window_days=window,
                                   min_periods=min(3, len(valid)))
    base = base.dropna(subset=["baseline"])
    return float(base["baseline"].iloc[-1]) if not base.empty else None


for family_key, family_label, family_metrics in metrics.families():
    if not family_metrics:
        continue
    st.header(family_label)
    for m in family_metrics:
        if m.key == "steps" and real_steps_goal is not None:
            m = dataclasses.replace(m, target=real_steps_goal)
        with st.expander(f"{m.label}  ·  {m.short}", expanded=False):
            st.write(m.what)
            st.caption(m.how_read)
            info_cols = st.columns(3)
            info_cols[0].metric("Provenance", m.provenance)
            info_cols[1].metric("Sens", m.direction_label)
            baseline_val = _current_baseline(m)
            info_cols[2].metric("Ta baseline actuelle", m.format(baseline_val) if baseline_val is not None else "—")
            extra = []
            if m.target is not None:
                extra.append(f"Objectif : {m.format(m.target)}")
            if m.good_range is not None:
                lo, hi = m.good_range
                extra.append(f"Plage cible : {m.format(lo)} – {m.format(hi)}")
            if extra:
                st.caption(" · ".join(extra))
