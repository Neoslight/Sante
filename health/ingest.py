"""Ingestion idempotente d'un export Google Health dans DuckDB.

Usage:
    python -m health.ingest                 # ingère le dernier export sous data/exports
    python -m health.ingest data/exports/2026-07-25
    python -m health.ingest --all            # rejoue tous les exports (rapide si déjà ingérés)
    python -m health.ingest --rebuild-only   # ne fait que reconstruire les marts

Mécanisme : chaque fichier source est identifié par son SHA-256. Un fichier
déjà présent dans meta.ingest_log (même sous un autre export/chemin) est
sauté sans être relu. Si au moins un fichier d'un dataset est nouveau, tout
le dataset de cet export est rechargé et fusionné dans raw.<table> via un
EXCEPT (n'insère que les lignes réellement absentes) : rejouer un import ne
produit donc jamais de doublon.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import duckdb

from . import discovery, loaders, sources
from .config import (
    DB_PATH,
    DEVICE_START_DATE,
    HR_SAMPLES_FULL_DAY,
    PARTIAL_DAY_THRESHOLD,
    RENFO_ACTIVITY_NAMES,
    SOURCE_PRIORITY,
    SQL_DIR,
    TIMEZONE,
    WAREHOUSE_DIR,
)
from .enrich import build_strength_sets


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def get_connection() -> duckdb.DuckDBPyConnection:
    WAREHOUSE_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute("INSTALL icu")
    con.execute("LOAD icu")
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    con.execute("CREATE SCHEMA IF NOT EXISTS mart")
    con.execute("CREATE SCHEMA IF NOT EXISTS meta")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS meta.ingest_log (
            sha256 VARCHAR PRIMARY KEY,
            file_path VARCHAR,
            dataset VARCHAR,
            ingested_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )
    return con


def _already_logged(con: duckdb.DuckDBPyConnection, sha: str) -> bool:
    return con.execute("SELECT 1 FROM meta.ingest_log WHERE sha256 = ?", [sha]).fetchone() is not None


def _log_file(con: duckdb.DuckDBPyConnection, sha: str, file_path: Path, dataset: str) -> None:
    con.execute(
        "INSERT INTO meta.ingest_log (sha256, file_path, dataset) VALUES (?, ?, ?) "
        "ON CONFLICT (sha256) DO NOTHING",
        [sha, str(file_path), dataset],
    )


def ingest_dataset(con: duckdb.DuckDBPyConnection, google_root: Path, ds: sources.Dataset) -> str:
    """Ingère un dataset pour un export. Retourne un statut lisible."""
    files = loaders.find_files(google_root, ds)
    if not files:
        return "absent"

    shas = {f: file_sha256(f) for f in files}
    new_files = [f for f in files if not _already_logged(con, shas[f])]
    if not new_files:
        return "déjà ingéré (skip)"

    df = loaders.load_dataset(google_root, ds)
    if df is None or df.empty:
        for f in files:
            _log_file(con, shas[f], f, ds.name)
        return "vide"

    con.register("stage_df", df)
    table = f"raw.{ds.name}"
    exists = con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema='raw' AND table_name=?",
        [ds.name],
    ).fetchone()

    if not exists:
        con.execute(f"CREATE TABLE {table} AS SELECT * FROM stage_df")
        n_inserted = len(df)
    else:
        before = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        key = _row_key_expr(list(df.columns))
        con.execute(
            f"""
            INSERT INTO {table}
            SELECT s.* EXCLUDE (_row_key)
            FROM (
                SELECT *, {key} AS _row_key FROM stage_df
                QUALIFY row_number() OVER (PARTITION BY _row_key ORDER BY _source_file) = 1
            ) s
            ANTI JOIN (SELECT {key} AS _row_key FROM {table}) t USING (_row_key)
            """
        )
        after = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        n_inserted = after - before

    con.unregister("stage_df")

    for f in files:
        _log_file(con, shas[f], f, ds.name)

    return f"{n_inserted} nouvelle(s) ligne(s) (sur {len(df)} lues)"


def _row_key_expr(columns: list[str]) -> str:
    """Clé d'unicité d'une ligne, hors `_source_file`.

    `_source_file` fait partie de la ligne stockée : le `EXCEPT` d'origine
    considérait donc comme nouvelle une mesure identique arrivant sous un autre
    nom de fichier. Takeout redécoupe ses chunks mensuels d'un export à l'autre,
    ce qui aurait fini par dupliquer les lignes de chevauchement.
    """
    business = [c for c in columns if c != "_source_file"]
    parts = ", ".join(f"coalesce(CAST(\"{c}\" AS VARCHAR), chr(0))" for c in business)
    return f"concat_ws(chr(31), {parts})"


def ingest_export(con: duckdb.DuckDBPyConnection, export_dir: Path) -> None:
    google_root = discovery.google_health_root(export_dir)
    print(f"\n=== Export {export_dir.name} ===")
    for ds in sources.ALL_DATASETS:
        status = ingest_dataset(con, google_root, ds)
        print(f"  {ds.name:<40} {status}")


def install_sql_context(con: duckdb.DuckDBPyConnection) -> None:
    """Macros et tables de référence utilisées par les marts SQL.

    Créées depuis la config Python pour qu'il n'y ait qu'une seule source de
    vérité : `DEVICE_START_DATE` était auparavant recopié en dur dans quatre
    fichiers SQL et dans app/charts.py.
    """
    # Les timestamps sont stockés en UTC naïf (cf. loaders.parse_timestamps).
    # `ts AT TIME ZONE 'Europe/Paris'` seul INTERPRÈTE l'entrée comme de l'heure
    # de Paris et la rend dans le fuseau de session : c'est un aller-retour
    # identité, pas une conversion. Il faut d'abord ancrer en UTC.
    con.execute(
        f"CREATE OR REPLACE MACRO to_local(ts) AS "
        f"(ts AT TIME ZONE 'UTC' AT TIME ZONE '{TIMEZONE}')"
    )
    # Nommée `to_local_date` et non `local_date` : c'est aussi un nom de colonne
    # très courant dans les marts, et l'ambiguïté est un piège inutile.
    con.execute("CREATE OR REPLACE MACRO to_local_date(ts) AS (CAST(to_local(ts) AS DATE))")
    con.execute(f"CREATE OR REPLACE MACRO device_start() AS (DATE '{DEVICE_START_DATE}')")
    con.execute(f"CREATE OR REPLACE MACRO hr_samples_full_day() AS ({HR_SAMPLES_FULL_DAY}.0)")
    con.execute(f"CREATE OR REPLACE MACRO partial_day_threshold() AS ({PARTIAL_DAY_THRESHOLD})")

    con.execute(
        "CREATE OR REPLACE TABLE meta.source_priority "
        "(metric VARCHAR, data_source VARCHAR, priority INTEGER)"
    )
    rows = [
        (metric, source, rank)
        for metric, ordered in SOURCE_PRIORITY.items()
        for rank, source in enumerate(ordered)
    ]
    con.executemany("INSERT INTO meta.source_priority VALUES (?, ?, ?)", rows)

    con.execute("CREATE OR REPLACE TABLE meta.renfo_activity_names (activity_name VARCHAR)")
    con.executemany(
        "INSERT INTO meta.renfo_activity_names VALUES (?)",
        [(name,) for name in RENFO_ACTIVITY_NAMES],
    )


def rebuild_marts(con: duckdb.DuckDBPyConnection) -> None:
    print("\n=== Reconstruction des marts ===")
    install_sql_context(con)
    sql_files = sorted(SQL_DIR.glob("*.sql"))
    # Phase 1 (préfixe < "400") : marts SQL pures (sleep, daily, workouts).
    # Puis l'enrichissement Python (movements.yaml -> mart.strength_sets).
    # Puis phase 2 (préfixe >= "400") : marts dépendant de strength_sets (weekly).
    for sql_file in sql_files:
        if sql_file.name < "400":
            print(f"  {sql_file.name}")
            con.execute(sql_file.read_text(encoding="utf-8"))

    print("  mart.strength_sets (movements.yaml)")
    build_strength_sets(con)

    for sql_file in sql_files:
        if sql_file.name >= "400":
            print(f"  {sql_file.name}")
            con.execute(sql_file.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", nargs="?", help="Dossier d'export à ingérer")
    parser.add_argument("--all", action="store_true", help="Ingérer tous les exports sous data/exports")
    parser.add_argument("--rebuild-only", action="store_true", help="Ne reconstruire que les marts")
    parser.add_argument(
        "--reparse",
        action="store_true",
        help="Vider les tables raw.* et le journal d'ingestion pour tout relire "
             "(nécessaire quand la logique de parsing change : le skip par SHA-256 "
             "empêche sinon un fichier déjà vu d'être relu)",
    )
    args = parser.parse_args(argv)

    con = get_connection()

    if args.reparse:
        print("=== Purge des tables raw.* (--reparse) ===")
        for ds in sources.ALL_DATASETS:
            con.execute(f"DROP TABLE IF EXISTS raw.{ds.name}")
        con.execute("DELETE FROM meta.ingest_log")

    if not args.rebuild_only:
        if args.all:
            exports = discovery.list_exports()
            if not exports:
                print("Aucun export trouvé sous data/exports/", file=sys.stderr)
                sys.exit(1)
            for export_dir in exports:
                ingest_export(con, export_dir)
        elif args.export:
            ingest_export(con, Path(args.export))
        else:
            export_dir = discovery.latest_export()
            if export_dir is None:
                print("Aucun export trouvé sous data/exports/", file=sys.stderr)
                sys.exit(1)
            ingest_export(con, export_dir)

    rebuild_marts(con)
    con.close()
    print("\nOK.")


if __name__ == "__main__":
    main()
