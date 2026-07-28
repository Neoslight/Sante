"""Lecture du profil utilisateur depuis la base plutôt que du dict codé en dur
`config.PROFILE`.

`get_profile(con)` lit `raw.user_profile` (ingéré depuis Your Profile/
Profile.csv) et retombe sur `config.PROFILE` si la table est absente (export
pas encore ingéré, ou base de test minimale). Poids et taille sont ensuite
recoupés avec les dernières mesures de `raw.weight` / `raw.height`, plus
fiables que la valeur déclarative du profil.
"""
from __future__ import annotations

import duckdb

from . import config


def _table_exists(con: duckdb.DuckDBPyConnection, schema: str, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = ? AND table_name = ?",
        [schema, table],
    ).fetchone() is not None


def _as_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_profile(con: duckdb.DuckDBPyConnection) -> dict:
    """Retourne le profil utilisateur : sexe, date de naissance, taille, poids,
    longueur de foulée marche/course, fuseau horaire, début de semaine.

    Repli sur `config.PROFILE` (valeurs par défaut écrites à la main) champ par
    champ si `raw.user_profile` est absent ou vide.
    """
    profile: dict = dict(config.PROFILE)
    profile.setdefault("stride_length_walking_cm", None)
    profile.setdefault("stride_length_running_cm", None)
    profile.setdefault("start_of_week", "MONDAY")
    profile.setdefault("timezone", config.TIMEZONE)

    if _table_exists(con, "raw", "user_profile"):
        row = con.execute(
            """
            SELECT gender, date_of_birth, height, weight,
                   stride_length_walking, stride_length_running,
                   timezone, start_of_week
            FROM raw.user_profile
            LIMIT 1
            """
        ).fetchone()
        if row is not None:
            sex, birth_date, height_cm, weight_kg, stride_walk, stride_run, tz, sow = row
            profile["sex"] = sex or profile["sex"]
            profile["birth_date"] = birth_date or profile["birth_date"]
            profile["height_cm"] = _as_float(height_cm) or profile["height_cm"]
            profile["weight_kg"] = _as_float(weight_kg) or profile["weight_kg"]
            profile["stride_length_walking_cm"] = _as_float(stride_walk)
            profile["stride_length_running_cm"] = _as_float(stride_run)
            profile["timezone"] = tz or profile["timezone"]
            profile["start_of_week"] = sow or profile["start_of_week"]

    # Poids/taille les plus récents mesurés (balance/appli), en grammes et
    # millimètres dans raw.* -- plus fiables que la valeur déclarative du
    # profil, qui n'est mise à jour qu'à la main dans l'appli Fitbit.
    if _table_exists(con, "raw", "weight"):
        w = con.execute(
            "SELECT try_cast(weight_grams AS DOUBLE) / 1000.0 FROM raw.weight "
            "WHERE timestamp IS NOT NULL ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if w is not None and w[0] is not None:
            profile["weight_kg"] = w[0]
    if _table_exists(con, "raw", "height"):
        h = con.execute(
            "SELECT try_cast(height_millimeters AS DOUBLE) / 10.0 FROM raw.height "
            "WHERE timestamp IS NOT NULL ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if h is not None and h[0] is not None:
            profile["height_cm"] = h[0]

    return profile
