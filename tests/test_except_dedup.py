"""Test unitaire, isolé des vraies données, du mécanisme de fusion utilisé
par ingest.ingest_dataset : `INSERT ... SELECT * FROM stage EXCEPT SELECT *
FROM table`. Vérifie qu'un import qui recouvre partiellement les données
déjà présentes n'ajoute que les lignes réellement nouvelles."""
import duckdb
import pandas as pd


def test_except_insert_only_adds_new_rows():
    con = duckdb.connect(":memory:")

    batch1 = pd.DataFrame({"timestamp": pd.to_datetime(["2026-06-17", "2026-06-18", "2026-06-19"]),
                            "value": [1, 2, 3]})
    con.register("stage", batch1)
    con.execute("CREATE TABLE t AS SELECT * FROM stage")
    con.unregister("stage")
    assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 3

    # Réimport du même fichier (export rejoué) : ne doit rien ajouter.
    con.register("stage", batch1)
    con.execute("INSERT INTO t SELECT * FROM stage EXCEPT SELECT * FROM t")
    con.unregister("stage")
    assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 3

    # Nouvel export qui recouvre partiellement (18-19 déjà là) + apporte le 20.
    batch2 = pd.DataFrame({"timestamp": pd.to_datetime(["2026-06-18", "2026-06-19", "2026-06-20"]),
                            "value": [2, 3, 4]})
    con.register("stage", batch2)
    con.execute("INSERT INTO t SELECT * FROM stage EXCEPT SELECT * FROM t")
    con.unregister("stage")

    rows = con.execute("SELECT value FROM t ORDER BY value").fetchall()
    assert [r[0] for r in rows] == [1, 2, 3, 4], "doublons ou perte de lignes lors du merge incrémental"

    con.close()
