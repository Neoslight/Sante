"""Enrichissements nécessitant un mapping externe (movements.yaml) plutôt
que du SQL pur : mart.strength_sets (groupe musculaire par set).
"""
from __future__ import annotations

import duckdb
import pandas as pd
import yaml

from .config import DEVICE_START_DATE, MOVEMENTS_YAML


def _load_mapping() -> dict:
    with open(MOVEMENTS_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _resolve_group(movement: str | None, segment_name: str | None, mapping: dict) -> str:
    movements = mapping.get("movements", {})
    if movement and movement in movements:
        return movements[movement]

    name = (segment_name or "").lower()
    for rule in mapping.get("keywords", []):
        if any(kw.lower() in name for kw in rule["contains"]):
            return rule["group"]

    return mapping.get("default", "autre")


def build_strength_sets(con: duckdb.DuckDBPyConnection) -> None:
    # La source ne renseigne `segment_start` que sur 54 des 172 segments de
    # travail (elle remplit en revanche systématiquement les bornes des segments
    # REST intercalés). Un segment de travail commence là où le repos précédent
    # se termine : on reconstruit donc le début manquant par LAG sur la fin du
    # segment précédent, en ordonnant l'ensemble WORK+REST de la séance.
    # Sans cela, 69 % des sets n'ont pas de durée et deux groupes musculaires
    # entiers (haut_du_corps, cou_epaules) sont NULL toutes les semaines.
    df = con.execute(
        f"""
        WITH segments AS (
            SELECT
                workout_name,
                interval_start,
                segment_name,
                segment_type,
                segment_movement,
                round_name,
                segment_start,
                coalesce(segment_end, set_end) AS segment_end_filled
            FROM raw.workout_summaries
            WHERE interval_start IS NOT NULL
              AND to_local_date(interval_start) >= DATE '{DEVICE_START_DATE}'
        ),
        chained AS (
            SELECT *,
                coalesce(
                    segment_start,
                    lag(segment_end_filled) OVER (
                        PARTITION BY workout_name, interval_start
                        ORDER BY segment_end_filled
                    ),
                    interval_start
                ) AS segment_start_filled
            FROM segments
        )
        SELECT
            workout_name,
            to_local_date(interval_start) AS local_date,
            to_local(interval_start) AS session_start_local,
            round_name,
            segment_name,
            segment_movement,
            to_local(segment_start_filled) AS segment_start,
            to_local(segment_end_filled) AS segment_end,
            segment_start IS NULL AND segment_end_filled IS NOT NULL AS duration_is_estimated,
            -- Une durée reconstruite implausible (>15 min pour un set) est
            -- laissée à NULL plutôt que d'inventer du volume. Certaines séances
            -- (ex. "Routine Quotidien Renforcement Cou & Épaules") n'ont AUCUN
            -- horodatage à la source : ces sets restent sans durée mais doivent
            -- rester comptés en nombre d'exécutions.
            CASE
                WHEN date_diff('second', segment_start_filled, segment_end_filled) <= 0 THEN NULL
                WHEN segment_start IS NULL
                     AND date_diff('second', segment_start_filled, segment_end_filled) > 900 THEN NULL
                WHEN date_diff('second', segment_start_filled, segment_end_filled) > 3600 THEN NULL
                ELSE date_diff('second', segment_start_filled, segment_end_filled)
            END AS duration_seconds
        FROM chained
        WHERE segment_type = 'WORKOUT_SEGMENT_TYPE_WORK'
          AND segment_name IS NOT NULL
        ORDER BY interval_start, segment_end_filled
        """
    ).df()

    mapping = _load_mapping()
    df["muscle_group"] = [
        _resolve_group(m, n, mapping) for m, n in zip(df["segment_movement"], df["segment_name"])
    ]

    unmapped = sorted(
        set(
            zip(df.loc[df["muscle_group"] == mapping.get("default", "autre"), "segment_movement"],
                df.loc[df["muscle_group"] == mapping.get("default", "autre"), "segment_name"])
        )
    )
    if unmapped:
        print("  [movements.yaml] mouvements non mappés (groupe 'autre') :")
        for movement, name in unmapped:
            print(f"    - segment_movement={movement!r} segment_name={name!r}")

    con.register("strength_sets_df", df)
    con.execute("CREATE OR REPLACE TABLE mart.strength_sets AS SELECT * FROM strength_sets_df")
    con.unregister("strength_sets_df")
