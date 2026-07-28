"""Ce en quoi on a le droit d'avoir confiance — vérifié.

Ces règles vivaient dans `app/Bilan_du_jour.py`, où elles étaient pures mais
intestables : une page Streamlit ne s'importe pas, et leur seul filet était un
test de fumée qui vérifie l'absence d'exception. Elles décident pourtant ce qui
entre dans une normale et ce qui entre dans le modèle de forme — c'est-à-dire
le chiffre le plus visible de l'application.
"""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from health import quality


def _frame(n=40, load=20.0, partial=(), missing=()) -> pd.DataFrame:
    days = [dt.date(2026, 6, 1) + dt.timedelta(days=i) for i in range(n)]
    return pd.DataFrame({
        "local_date": pd.to_datetime(days),
        "cardio_load_total": [load] * n,
        "is_partial_day": [d in partial for d in days],
        "is_missing_day": [d in missing for d in days],
    })


# --- ce qui compte comme mesuré ---------------------------------------------
def test_a_frame_without_quality_columns_is_taken_at_face_value():
    """Comportement correct pour une table dérivée qui a déjà fait le tri —
    et non un silence sur un problème."""
    df = pd.DataFrame({"local_date": pd.to_datetime(["2026-06-01"]), "v": [1.0]})
    assert quality.is_measured(df).all()
    assert quality.count_measured(df) == 1


def test_count_measured_ignores_the_days_the_watch_missed():
    """`len(df)` compte les lignes du calendrier, pas la profondeur des données :
    annoncer « 39 jours d'historique » quand deux d'entre eux n'ont presque rien
    enregistré promet une base qui n'existe pas."""
    df = _frame(n=10, partial=(dt.date(2026, 6, 3),), missing=(dt.date(2026, 6, 5),))
    assert len(df) == 10
    assert quality.count_measured(df) == 8


# --- ce qui a le droit de définir une normale --------------------------------
def test_reference_frame_drops_poorly_covered_days():
    df = _frame(n=10, partial=(dt.date(2026, 6, 3), dt.date(2026, 6, 4)))
    assert len(quality.reference_frame(df)) == 8


def test_reference_frame_keeps_the_day_under_judgement_even_if_partial():
    """L'invariant dont dépendent tous les `.iloc[-1]` des appelants : le jour
    qu'on juge doit rester la DERNIÈRE ligne du cadre. S'il en sortait, la
    couleur et le z-score d'une tuile décriraient silencieusement un autre jour
    que celui dont la page affiche la valeur."""
    judged = dt.date(2026, 6, 10)
    df = _frame(n=10, partial=(judged,))
    kept = quality.reference_frame(df, keep=judged)
    assert len(kept) == 10
    assert pd.to_datetime(kept["local_date"]).dt.date.iloc[-1] == judged
    # Sans `keep`, il sort — et la dernière ligne devient la veille.
    assert pd.to_datetime(quality.reference_frame(df)["local_date"]).dt.date.iloc[-1] != judged


# --- la charge reconstruite --------------------------------------------------
def test_impute_replaces_the_load_of_a_poorly_covered_day():
    """Le défaut d'origine : une journée à 66 % de couverture enregistrait une
    charge proche de la médiane et se lisait comme une vraie journée calme, ce
    qui gonflait la fraîcheur du lendemain."""
    partial = dt.date(2026, 7, 5)
    df = _frame(n=40, load=20.0, partial=(partial,))
    df.loc[pd.to_datetime(df["local_date"]).dt.date == partial, "cardio_load_total"] = 5.0
    out = quality.impute_partial_load(df)
    row = out.loc[pd.to_datetime(out["local_date"]).dt.date == partial]
    assert row["cardio_load_total"].iloc[0] == pytest.approx(20.0)
    assert bool(row["load_imputed"].iloc[0])


def test_impute_never_touches_a_measured_day():
    df = _frame(n=40, load=20.0, partial=(dt.date(2026, 7, 5),))
    df.loc[3, "cardio_load_total"] = 99.0  # journée mesurée, valeur extrême
    out = quality.impute_partial_load(df)
    assert out.loc[3, "cardio_load_total"] == 99.0
    assert not out.loc[3, "load_imputed"]


def test_impute_only_looks_backwards():
    """Une charge reconstruite à partir de jours qui n'avaient pas encore eu
    lieu ferait dire au passé ce que seul l'avenir savait — la même règle que
    celle qui interdit `full_daily` au modèle de forme."""
    partial = dt.date(2026, 6, 20)
    df = _frame(n=40, load=10.0, partial=(partial,))
    idx = pd.to_datetime(df["local_date"]).dt.date > partial
    df.loc[idx, "cardio_load_total"] = 500.0  # avenir spectaculaire
    out = quality.impute_partial_load(df)
    imputed = out.loc[pd.to_datetime(out["local_date"]).dt.date == partial, "cardio_load_total"]
    assert imputed.iloc[0] == pytest.approx(10.0), "l'avenir a fui dans le passé"


def test_impute_gives_up_rather_than_invent_on_a_short_history():
    """Sous cinq journées mesurées, la médiane ne veut rien dire : mieux vaut
    la charge sous-enregistrée — au moins elle a été mesurée."""
    df = _frame(n=3, partial=(dt.date(2026, 6, 1),))
    out = quality.impute_partial_load(df)
    assert not out["load_imputed"].any()


def test_impute_marks_what_it_reconstructed():
    """Sans ce drapeau, l'interface ne peut pas distinguer une mesure d'une
    reconstruction — et une reconstruction silencieuse est un mensonge."""
    df = _frame(n=40, partial=(dt.date(2026, 7, 5),))
    out = quality.impute_partial_load(df)
    assert "load_imputed" in out.columns
    assert out["load_imputed"].sum() == 1


def test_impute_is_a_noop_on_a_fully_measured_history():
    df = _frame(n=40)
    out = quality.impute_partial_load(df)
    assert not out["load_imputed"].any()
    assert np.allclose(out["cardio_load_total"], df["cardio_load_total"])


def test_impute_does_not_borrow_from_other_partial_days():
    """Imputer depuis une fenêtre qui contient d'autres journées partielles
    propagerait leur sous-comptage de proche en proche."""
    partials = [dt.date(2026, 7, 1) + dt.timedelta(days=i) for i in range(3)]
    df = _frame(n=40, load=20.0, partial=tuple(partials))
    df.loc[pd.to_datetime(df["local_date"]).dt.date.isin(partials), "cardio_load_total"] = 1.0
    out = quality.impute_partial_load(df)
    got = out.loc[pd.to_datetime(out["local_date"]).dt.date.isin(partials), "cardio_load_total"]
    assert np.allclose(got, 20.0), "une journée partielle a servi de référence à une autre"
