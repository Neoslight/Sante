"""Tests de app/queries.py — spécifiquement la correction d'âge de bmr_kcal().

L'ancien calcul faisait `now.year - birth.year`, faux d'un an la moitié de
l'année (tant que l'anniversaire n'est pas encore passé). Ces tests comparent
`bmr_kcal()` à un calcul d'âge fait indépendamment (comparaison de
(mois, jour), pas seulement de l'année) pour verrouiller la correction.
"""
import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import queries  # noqa: E402
from health.profile import get_profile  # noqa: E402


@pytest.fixture(scope="module")
def profile():
    result = get_profile(queries.get_connection())
    yield result
    # `get_connection()` est mis en cache par Streamlit (@st.cache_resource) et
    # reste ouvert pour tout le process sinon -- une connexion DuckDB laissée
    # ouverte ici bloquerait la connexion EN ÉCRITURE que
    # test_ingest_idempotence.py ouvre plus loin dans la même session pytest.
    queries.get_connection().close()
    queries.get_connection.clear()


def _exact_age(birth: dt.date, today: dt.date) -> int:
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def test_bmr_kcal_matches_mifflin_st_jeor_with_exact_age(profile):
    birth = pd.Timestamp(profile["birth_date"]).date()
    today = dt.date.today()
    age = _exact_age(birth, today)
    sex_offset = 5 if str(profile.get("sex", "MALE")).upper().startswith("M") else -161
    expected = 10 * profile["weight_kg"] + 6.25 * profile["height_cm"] - 5 * age + sex_offset
    assert queries.bmr_kcal() == pytest.approx(expected)


def test_bmr_kcal_age_is_not_a_naive_year_subtraction(profile):
    """Régression directe du bug : si l'anniversaire n'est pas encore passé
    cette année, `now.year - birth.year` surestime l'âge de 1 -- et donc sous-
    estime le BMR de 5 kcal (le coefficient d'âge de Mifflin-St Jeor)."""
    birth = pd.Timestamp(profile["birth_date"]).date()
    today = dt.date.today()
    naive_age = today.year - birth.year
    correct_age = _exact_age(birth, today)
    if naive_age == correct_age:
        pytest.skip("L'anniversaire est déjà passé cette année : rien à distinguer aujourd'hui.")
    sex_offset = 5 if str(profile.get("sex", "MALE")).upper().startswith("M") else -161
    naive_bmr = 10 * profile["weight_kg"] + 6.25 * profile["height_cm"] - 5 * naive_age + sex_offset
    assert queries.bmr_kcal() == pytest.approx(naive_bmr + 5)


def test_bmr_kcal_accepts_explicit_weight_override(profile):
    default = queries.bmr_kcal()
    overridden = queries.bmr_kcal(weight_kg=profile["weight_kg"] + 10)
    assert overridden == pytest.approx(default + 100)  # +10 kg * facteur 10 de Mifflin-St Jeor
