"""Lecture générique des CSV de l'export : slugification des colonnes,
parsing des timestamps en UTC naïf, tout le reste en texte (le typage
numérique se fait plus tard dans les vues `mart.*` via TRY_CAST).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from .sources import Dataset

# Format des `dateTime` dans les exports JSON Fitbit ([{"dateTime": ...,
# "value": {...}}]) : "MM/DD/YY HH:MM:SS", sans indication de fuseau -- comme
# les colonnes "timestamp" à 00:00:00Z des CSV daily_*.csv, c'est déjà la date
# locale (cf. 200_daily.sql, CAST(timestamp AS DATE) sans to_local_date()).
FITBIT_JSON_DATETIME_FORMAT = "%m/%d/%y %H:%M:%S"

# `keep_default_na=False` empêche pandas de transformer des chaînes légitimes en
# NaN ; on réintroduit donc explicitement les seules sentinelles rencontrées dans
# l'export (Fitbit écrit littéralement "NaN" dans certaines colonnes de
# température, ce qui survivrait sinon jusqu'à un float NaN — et non un NULL —
# après TRY_CAST, contaminant les avg() SQL).
NA_VALUES = ["", "NaN", "nan", "null", "NULL", "N/A"]

# Au-delà de ce taux d'échec sur des valeurs sources non vides, on lève plutôt
# que de laisser `errors="coerce"` masquer une perte de données.
MAX_UNPARSED_TS_RATIO = 0.01


def slugify_col(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_")


def find_files(google_health_root: Path, ds: Dataset) -> list[Path]:
    return sorted((google_health_root / ds.folder).glob(ds.pattern))


def load_dataset(google_health_root: Path, ds: Dataset) -> pd.DataFrame | None:
    """Charge et concatène tous les fichiers d'un dataset pour un export.

    Retourne None si aucun fichier trouvé (dataset absent de cet export).
    """
    files = find_files(google_health_root, ds)
    if not files:
        return None

    if ds.fmt == "json":
        out = _load_json_files(files, ds)
    else:
        out = _load_csv_files(files)

    for col in ds.ts_cols:
        if col in out.columns:
            out[col] = parse_timestamps(out[col], dataset=ds.name, column=col)

    return out


def _load_csv_files(files: list[Path]) -> pd.DataFrame:
    frames = []
    for f in files:
        df = pd.read_csv(f, dtype=str, encoding="utf-8", keep_default_na=False, na_values=NA_VALUES)
        df.columns = [slugify_col(c) for c in df.columns]
        df["_source_file"] = f.name
        frames.append(df)
    return pd.concat(frames, ignore_index=True, sort=False)


def _load_json_files(files: list[Path], ds: Dataset) -> pd.DataFrame:
    """Charge des fichiers JSON Fitbit de la forme `[{"dateTime": ..., "value":
    {...}}, ...]`. `value` est aplati en colonnes via `ds.json_value_map`
    (clé source -> nom de colonne) ; tout le reste est renvoyé en texte, comme
    les CSV, pour rester typé plus tard via TRY_CAST dans les marts SQL.
    """
    value_map = ds.json_value_map or {}
    frames = []
    for f in files:
        records = json.loads(f.read_text(encoding="utf-8"))
        rows = []
        for rec in records:
            ts = pd.to_datetime(rec["dateTime"], format=FITBIT_JSON_DATETIME_FORMAT)
            row = {"timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ")}
            value = rec.get("value", {})
            if isinstance(value, dict):
                for k, v in value.items():
                    row[value_map.get(k, slugify_col(k))] = v
            else:
                row[value_map.get("value", "value")] = value
            rows.append(row)
        df = pd.DataFrame(rows)
        # Colonnes texte (dtype=str) pour rester cohérent avec le chemin CSV :
        # le typage numérique se fait via TRY_CAST dans les marts SQL.
        for col in df.columns:
            if col != "timestamp":
                df[col] = df[col].astype(str)
        df["_source_file"] = f.name
        frames.append(df)
    return pd.concat(frames, ignore_index=True, sort=False)


def parse_timestamps(raw: pd.Series, dataset: str = "", column: str = "") -> pd.Series:
    """Parse une colonne de timestamps ISO en TIMESTAMP UTC naïf.

    `format="ISO8601"` est indispensable : un même fichier Google Health mélange
    plusieurs précisions de fraction de seconde (`...:36.058Z`, `...:01Z`,
    `...:12.34Z`, `...:07.6Z`). Sans ce paramètre, pandas >= 2 infère un format
    unique depuis la première valeur et transforme silencieusement toutes les
    autres en NaT — c'est ce qui faisait disparaître 75 % de raw.steps.
    """
    parsed = pd.to_datetime(raw, format="ISO8601", utc=True, errors="coerce").dt.tz_localize(None)

    # Garde-fou : un échec de parsing ne doit plus jamais être silencieux.
    non_empty = raw.notna()
    n_source = int(non_empty.sum())
    if n_source:
        n_failed = int((non_empty & parsed.isna()).sum())
        if n_failed / n_source > MAX_UNPARSED_TS_RATIO:
            sample = raw[non_empty & parsed.isna()].head(3).tolist()
            raise ValueError(
                f"{dataset}.{column}: {n_failed}/{n_source} timestamps non parsés "
                f"({n_failed / n_source:.1%} > {MAX_UNPARSED_TS_RATIO:.1%}). Exemples : {sample}"
            )

    # Fitbit utilise parfois le "zéro" epoch (1970-01-01) comme valeur
    # sentinelle pour "non renseigné" plutôt que de laisser vide.
    return parsed.where(parsed >= pd.Timestamp("1971-01-01"))
