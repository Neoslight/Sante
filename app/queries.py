"""Accès DuckDB en lecture seule pour l'app Streamlit, avec cache."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from health.config import DB_PATH  # noqa: E402
from health.profile import get_profile  # noqa: E402


@st.cache_resource
def get_connection():
    import duckdb
    con = duckdb.connect(str(DB_PATH), read_only=True)
    con.execute("INSTALL icu")
    con.execute("LOAD icu")
    return con


@st.cache_data(ttl=300)
def run_query(sql: str, params: list | None = None) -> pd.DataFrame:
    return get_connection().execute(sql, params or []).df()


def daily(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM mart.daily"
    params = []
    if start and end:
        sql += " WHERE local_date BETWEEN ? AND ?"
        params = [start, end]
    sql += " ORDER BY local_date"
    return run_query(sql, params)


def sleep(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM mart.sleep"
    params = []
    if start and end:
        sql += " WHERE local_date BETWEEN ? AND ?"
        params = [start, end]
    sql += " ORDER BY local_date"
    return run_query(sql, params)


def workouts(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM mart.workouts"
    params = []
    if start and end:
        sql += " WHERE local_date BETWEEN ? AND ?"
        params = [start, end]
    sql += " ORDER BY start_local"
    return run_query(sql, params)


def strength_sessions(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM mart.strength_sessions"
    params = []
    if start and end:
        sql += " WHERE local_date BETWEEN ? AND ?"
        params = [start, end]
    sql += " ORDER BY start_local"
    return run_query(sql, params)


def strength_sets(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM mart.strength_sets"
    params = []
    if start and end:
        sql += " WHERE local_date BETWEEN ? AND ?"
        params = [start, end]
    return run_query(sql, params)


def weekly() -> pd.DataFrame:
    return run_query("SELECT * FROM mart.weekly ORDER BY week_start")


def date_bounds() -> tuple[pd.Timestamp, pd.Timestamp]:
    df = run_query("SELECT min(local_date) lo, max(local_date) hi FROM mart.daily")
    return df["lo"].iloc[0], df["hi"].iloc[0]


def steps_goal() -> float | None:
    """Dernier objectif de pas quotidien connu (mart.goals), ou None si absent.

    Remplace le 10 000 pas codé en dur : la vraie valeur vient de Activity
    Goals.csv (Fitbit), et peut donc changer si l'utilisateur ajuste son
    objectif."""
    df = run_query(
        "SELECT target FROM mart.goals WHERE goal_type = 'STEPS_GOAL' AND frequency = 'DAILY' "
        "ORDER BY end_date DESC LIMIT 1"
    )
    return float(df["target"].iloc[0]) if not df.empty else None


def goals(goal_type: str | None = None, frequency: str | None = None) -> pd.DataFrame:
    """Historique des objectifs Fitbit (mart.goals), filtrable par type
    (STEPS_GOAL, CALORIES_GOAL...) et/ou fréquence (DAILY, WEEKLY)."""
    sql = "SELECT * FROM mart.goals"
    clauses, params = [], []
    if goal_type:
        clauses.append("goal_type = ?")
        params.append(goal_type)
    if frequency:
        clauses.append("frequency = ?")
        params.append(frequency)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY goal_type, frequency, start_date"
    return run_query(sql, params)


def hr_zones(local_date: str | None = None) -> pd.DataFrame:
    """Bornes personnelles des zones de FC (mart.hr_zones) pour un jour donné,
    ou le dernier jour connu si `local_date` est omis -- ces bornes changent
    rarement d'un jour à l'autre, mais sont recalculées quotidiennement par
    Fitbit. Sert à dessiner les bandes de zones sur `charts.intraday_hr`."""
    if local_date:
        return run_query(
            "SELECT * FROM mart.hr_zones WHERE local_date = ? ORDER BY zone_order", [local_date]
        )
    return run_query(
        "SELECT * FROM mart.hr_zones WHERE local_date = (SELECT max(local_date) FROM mart.hr_zones) "
        "ORDER BY zone_order"
    )


def hrv_intraday(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """RMSSD intraday (mart.hrv_intraday, ~toutes les 5 min pendant le
    sommeil)."""
    sql = "SELECT * FROM mart.hrv_intraday"
    params = []
    if start and end:
        sql += " WHERE local_date BETWEEN ? AND ?"
        params = [start, end]
    sql += " ORDER BY timestamp_local"
    return run_query(sql, params)


def spo2_intraday(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """SpO2 intraday par minute (mart.spo2_intraday, essentiellement
    nocturne)."""
    sql = "SELECT * FROM mart.spo2_intraday"
    params = []
    if start and end:
        sql += " WHERE local_date BETWEEN ? AND ?"
        params = [start, end]
    sql += " ORDER BY timestamp_local"
    return run_query(sql, params)


def heart_rate_intraday(local_date: str, max_points: int = 2000) -> pd.DataFrame:
    """FC brute (raw.heart_rate) d'UN jour, sous-échantillonnée à ~max_points.

    Une journée pleine porte ~37 000 échantillons (health.config.HR_SAMPLES_
    FULL_DAY) : les envoyer tels quels au navigateur pour un graphe large de
    quelques centaines de pixels ne montrerait rien de plus qu'une version
    sous-échantillonnée, en beaucoup plus lent à charger. Le sous-échantillonnage
    se fait dans DuckDB (une ligne conservée tous les N, via row_number) plutôt
    que côté pandas, pour ne jamais rapatrier le brut en premier lieu."""
    sql = """
        WITH base AS (
            SELECT
                to_local(timestamp) AS timestamp_local,
                try_cast(beats_per_minute AS DOUBLE) AS bpm,
                row_number() OVER (ORDER BY timestamp) AS rn,
                count(*) OVER () AS n
            FROM raw.heart_rate
            WHERE to_local_date(timestamp) = ?
        )
        SELECT timestamp_local, bpm
        FROM base
        WHERE mod(rn, CAST(GREATEST(1, CEIL(n / ?::DOUBLE)) AS BIGINT)) = 0
        ORDER BY timestamp_local
    """
    return run_query(sql, [local_date, max_points])


def bmr_kcal(weight_kg: float | None = None) -> float:
    """Métabolisme de base, formule de Mifflin-St Jeor.

    Poids, taille, sexe et date de naissance viennent de
    `health.profile.get_profile` (profil réel Fitbit, recoupé avec les
    dernières pesées) plutôt que du dict `config.PROFILE` codé en dur. L'âge
    était calculé comme `now.year - birth.year`, faux de un an pendant la
    moitié de l'année (avant l'anniversaire) : corrigé ici en comparant
    (mois, jour)."""
    profile = get_profile(get_connection())
    w = weight_kg if weight_kg is not None else profile["weight_kg"]
    h = profile["height_cm"]

    birth = pd.Timestamp(profile["birth_date"]).date()
    today = dt.date.today()
    age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))

    sex_offset = 5 if str(profile.get("sex", "MALE")).upper().startswith("M") else -161
    return 10 * w + 6.25 * h - 5 * age + sex_offset


def delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or pd.isna(current) or pd.isna(previous):
        return None
    return current - previous
