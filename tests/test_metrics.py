"""Cohérence du registre de métriques avec le schéma réel des marts.

Le registre est la source de vérité de tout l'affichage : une clé qui ne
correspond à aucune colonne produirait un graphe vide, silencieusement.
"""
import pytest

from health import metrics

# Métriques calculées à la volée par health/stats.py : elles n'existent dans
# aucune table, c'est normal.
COMPUTED_ONLY = {"tsb", "ctl", "atl", "sleep_debt"}


def _columns(con, table: str) -> set[str]:
    rows = con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'mart' AND table_name = ?", [table]
    ).fetchall()
    return {r[0] for r in rows}


def test_every_metric_key_maps_to_a_real_column(con):
    known = _columns(con, "daily") | _columns(con, "weekly") | COMPUTED_ONLY
    unknown = sorted(k for k in metrics.METRICS if k not in known)
    assert unknown == [], f"clés du registre sans colonne correspondante : {unknown}"


def test_every_metric_declares_a_known_family():
    for m in metrics.METRICS.values():
        assert m.family in metrics.FAMILIES, f"{m.key} : famille inconnue {m.family!r}"


def test_every_metric_is_documented():
    """`what` et `how_read` alimentent la page Glossaire : une métrique sans
    explication est exactement le problème qu'on cherche à corriger."""
    for m in metrics.METRICS.values():
        assert len(m.what) > 30, f"{m.key} : description trop courte"
        assert len(m.how_read) > 40, f"{m.key} : mode de lecture trop court"
        assert m.provenance in {
            metrics.PROV_MEASURE, metrics.PROV_FITBIT_SCORE,
            metrics.PROV_FITBIT_DAILY, metrics.PROV_COMPUTED,
        }, f"{m.key} : provenance non typée"


def test_direction_and_baseline_are_coherent():
    for m in metrics.METRICS.values():
        assert m.direction in (-1, 0, 1), m.key
        assert m.baseline in ("personal", "target", "fixed", "none"), m.key
        if m.baseline == "target":
            assert m.target is not None or m.key in {"calories_total"}, (
                f"{m.key} : baseline 'target' sans cible"
            )
        if m.baseline == "fixed":
            assert m.good_range is not None, f"{m.key} : baseline 'fixed' sans plage"
        if m.good_range:
            assert m.good_range[0] < m.good_range[1], m.key


def test_palette_index_stays_inside_the_categorical_palette():
    for m in metrics.METRICS.values():
        assert 0 <= m.palette_index <= 7, f"{m.key} : index de palette hors bornes"


def test_explorer_defaults_are_registered():
    for key in metrics.EXPLORER_DEFAULT:
        assert key in metrics.METRICS, key


def test_format_handles_missing_values():
    m = metrics.require("resting_hr")
    assert m.format(None) == "—"
    assert m.format(float("nan")) == "—"
    assert m.format(58) == "58 bpm"


def test_rounded_makes_on_screen_arithmetic_add_up():
    """« 35,0 → 28,5 » accompagné d'un « −6,4 » : l'écart était calculé sur les
    valeurs brutes, et le lecteur qui le refait de tête trouve −6,5."""
    m = metrics.require("ctl")
    was, now = 34.96, 28.54
    assert m.format(was, with_unit=False) == "35,0"
    assert m.format(now, with_unit=False) == "28,5"
    # Sur les valeurs brutes, l'écart affiché contredit les deux bornes
    # affichées : c'est le défaut que `rounded` existe pour supprimer.
    assert m.format_delta(now - was) == "-6,4"
    assert m.format_delta(m.rounded(now) - m.rounded(was)) == "-6,5"


def test_rounded_follows_the_precision_of_each_format():
    assert metrics.require("resting_hr").rounded(59.6) == 60      # "{:.0f}"
    assert metrics.require("vo2_max").rounded(54.24) == 54.2      # "{:.1f}"
    assert metrics.require("vo2_max").rounded(None) is None


def test_require_raises_on_unknown_key():
    with pytest.raises(KeyError):
        metrics.require("inexistant")
