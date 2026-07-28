"""Calculs statistiques mis en cache, à l'usage des pages.

`health/stats.py` reste PUR : il n'importe pas Streamlit, et c'est ce qui
permet de le tester sans serveur ni session. Le cache, lui, est une propriété
de l'application — il vit donc ici, dans une couche mince qui n'ajoute aucune
règle et se contente d'éviter de refaire deux fois le même travail.

Pourquoi c'était nécessaire. Chaque rendu de la grille recalculait une fenêtre
glissante par tuile pour la normale, plus une autre pour le z-score, sur tout
l'historique — et le MAD passe par un `.apply()` Python, donc coûte cher :

     39 jours ->    51 ms       (invisible)
    365 jours ->   170 ms
   1825 jours ->   695 ms       (perceptible à chaque clic de jour)

Deux corrections se cumulent : `stats.robust_z` accepte désormais une baseline
déjà calculée (moitié du travail supprimée), et ce cache absorbe le reste dès
le second rendu. Une navigation d'un jour à l'autre ne recalcule plus que ce
qui a réellement changé.

La clé de cache inclut la dernière date et la longueur de l'historique : deux
appels sur la même métrique et le même historique sont identiques, et le seul
moyen que l'historique change sans que ces deux valeurs bougent serait une
réécriture du passé — auquel cas le TTL de `queries` a de toute façon expiré.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from health import stats  # noqa: E402


@st.cache_data(ttl=300, show_spinner=False)
def _baseline_cached(
    values: tuple, dates: tuple, window_days: int, min_periods: int,
) -> pd.DataFrame:
    """Corps mis en cache, sur des arguments HACHABLES.

    Streamlit sait hacher un DataFrame, mais en le sérialisant à chaque appel —
    ce qui, sur l'historique complet et huit métriques, coûte une part notable
    de ce qu'on cherche à économiser. Deux tuples de scalaires se hachent, eux,
    sans copie.
    """
    df = pd.DataFrame({"local_date": pd.to_datetime(list(dates)), "v": list(values)})
    return stats.rolling_baseline(df, "v", "local_date", window_days, min_periods)


def baseline_and_z(
    df: pd.DataFrame, value_col: str, date_col: str = "local_date",
    window_days: int = 28, min_periods: int = 5,
) -> tuple[pd.DataFrame, pd.Series]:
    """`(baseline, z)` pour une métrique — les deux d'un coup, calculés une fois.

    Les tuiles ont besoin des deux (le pointillé et la couleur), et il est
    essentiel qu'ils viennent de la MÊME médiane : c'est ce qui garantit qu'une
    tuile ne puisse pas annoncer une hausse au-dessus d'un point situé sous son
    pointillé.
    """
    if value_col not in df.columns or date_col not in df.columns:
        empty = pd.DataFrame(columns=["baseline", "sigma", "lower", "upper"])
        return empty, pd.Series(dtype=float)
    valid = df[[date_col, value_col]].dropna()
    base = _baseline_cached(
        tuple(valid[value_col].astype(float)),
        tuple(pd.to_datetime(valid[date_col]).dt.strftime("%Y-%m-%d")),
        window_days, min_periods,
    )
    z = stats.robust_z(
        valid.rename(columns={value_col: "v"}), "v", date_col,
        window_days, min_periods, baseline=base,
    )
    return base, z
