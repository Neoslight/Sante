"""Rejouer l'ingestion sur des données déjà présentes ne doit produire
aucune ligne supplémentaire ni erreur : c'est la garantie qui permet de
relancer `update.ps1` à chaque nouvel export sans risque de doublons."""
import duckdb

from health import ingest
from health.config import DB_PATH
from tests.conftest import RAW_TABLES


def _counts(connection: duckdb.DuckDBPyConnection) -> dict[str, int]:
    return {t: connection.execute(f"SELECT count(*) FROM raw.{t}").fetchone()[0] for t in RAW_TABLES}


def test_rerunning_ingest_all_is_a_noop():
    con = duckdb.connect(str(DB_PATH))
    before = _counts(con)

    ingest.main(["--all"])

    after = _counts(con)
    con.close()

    assert before == after, "Rejouer l'ingestion a changé le nombre de lignes dans raw.*"


def test_rerunning_ingest_all_keeps_mart_row_counts_stable():
    con = duckdb.connect(str(DB_PATH))
    mart_tables = ["daily", "sleep", "workouts", "strength_sessions", "strength_sets", "weekly"]
    before = {t: con.execute(f"SELECT count(*) FROM mart.{t}").fetchone()[0] for t in mart_tables}

    ingest.main(["--all"])

    after = {t: con.execute(f"SELECT count(*) FROM mart.{t}").fetchone()[0] for t in mart_tables}
    con.close()

    assert before == after
