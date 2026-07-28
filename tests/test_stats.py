"""Tests de la couche statistique sur des séries synthétiques à réponse connue.

Contrairement aux tests de marts, ceux-ci ne dépendent pas de l'export réel :
ils vérifient les formules elles-mêmes.
"""
import math

import numpy as np
import pandas as pd
import pytest

from health import stats


def _daily(values, start="2026-01-01", col="v"):
    dates = pd.date_range(start, periods=len(values), freq="D")
    return pd.DataFrame({"local_date": dates, col: values})


# --- Loi de Student ---------------------------------------------------------
@pytest.mark.parametrize(
    "t_stat, dof, expected",
    [
        (2.228, 10, 0.05),    # quantile 97,5 % à 10 ddl
        (2.086, 20, 0.05),    # idem à 20 ddl
        (1.960, 100000, 0.05),  # limite normale
        (0.0, 10, 1.0),
    ],
)
def test_student_p_values_match_reference_table(t_stat, dof, expected):
    assert stats._t_two_sided_p(t_stat, dof) == pytest.approx(expected, abs=1e-3)


def test_student_critical_value_matches_reference_table():
    assert stats._t_critical_95(10) == pytest.approx(2.228, abs=1e-3)
    assert stats._t_critical_95(30) == pytest.approx(2.042, abs=1e-3)


# --- Tendance ---------------------------------------------------------------
def test_trend_recovers_a_known_slope():
    # +2 par jour = +14 par semaine, exactement.
    df = _daily([10 + 2 * i for i in range(30)])
    t = stats.trend(df, "v")
    assert t.slope_per_day == pytest.approx(2.0)
    assert t.slope_per_week == pytest.approx(14.0)
    assert t.r2 == pytest.approx(1.0)
    assert t.is_significant
    assert t.direction == "hausse"


def test_trend_on_pure_noise_is_not_significant():
    rng = np.random.default_rng(0)
    df = _daily(rng.normal(50, 5, 60))
    t = stats.trend(df, "v")
    assert not t.is_significant
    # Ni « stable » ni « plateau » : sur du bruit pur la pente réelle EST nulle,
    # mais le test ne le démontre pas — il ne rejette pas zéro, ce qui est autre
    # chose. Le libellé doit rester indiscernable de celui d'une vraie pente
    # trop faible pour ressortir.
    assert t.direction == "indéterminée"
    assert "aucune tendance détectable" in t.label()
    assert "stable" not in t.label()


def test_trend_confidence_interval_brackets_the_slope():
    rng = np.random.default_rng(1)
    df = _daily([100 + 1.5 * i + rng.normal(0, 3) for i in range(45)])
    t = stats.trend(df, "v")
    assert t.ci_low_per_week < t.slope_per_week < t.ci_high_per_week
    assert t.ci_low_per_week < 1.5 * 7 < t.ci_high_per_week


def test_trend_refuses_to_conclude_on_too_few_points():
    assert stats.trend(_daily([1, 2]), "v") is None
    t = stats.trend(_daily([1, 5, 2, 8, 3]), "v")
    assert not t.is_significant
    assert "trop peu de points" in t.label()


# --- Baseline et z-score ----------------------------------------------------
def test_rolling_baseline_is_calendar_aware_not_row_aware():
    """Une série trouée ne doit pas voir sa fenêtre "28 jours" s'étaler sur des
    mois : c'est le bug qui rendait la moyenne 7 j de l'ACWR (NULL 11 jours sur
    39) incomparable d'un point à l'autre."""
    dates = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-03-01", "2026-03-02"])
    df = pd.DataFrame({"local_date": dates, "v": [10.0, 10.0, 50.0, 50.0]})
    base = stats.rolling_baseline(df, "v", window_days=28, min_periods=1)
    # Le 1er mars ne doit voir que lui-même, pas les valeurs de janvier.
    assert base.loc[2, "baseline"] == pytest.approx(50.0)
    assert base.loc[2, "n_window"] == 1


def test_robust_z_is_unmoved_by_a_single_outlier():
    values = [50.0] * 29 + [500.0]
    df = _daily(values)
    z = stats.robust_z(df, "v", window_days=28, min_periods=5)
    # La médiane reste à 50 : l'aberration est signalée, pas absorbée.
    assert z.iloc[-1] > 3
    assert abs(z.iloc[-2]) < 1


def test_status_from_z_respects_direction():
    # HRV : plus haut = mieux
    assert stats.status_from_z(-2.5, direction=1) == "critical"
    assert stats.status_from_z(2.5, direction=1) == "excellent"
    # FC de repos : plus haut = moins bien
    assert stats.status_from_z(2.5, direction=-1) == "critical"
    assert stats.status_from_z(-2.5, direction=-1) == "excellent"
    assert stats.status_from_z(None) == "neutral"
    assert stats.status_from_z(1.0, direction=0) == "neutral"


# --- Modèle de forme --------------------------------------------------------
def test_ctl_and_atl_converge_to_a_constant_load():
    df = _daily([10.0] * 400, col="cardio_load_total")
    out = stats.ctl_atl_tsb(df)
    assert out["ctl"].iloc[-1] == pytest.approx(10.0, abs=0.1)
    assert out["atl"].iloc[-1] == pytest.approx(10.0, abs=0.1)
    # À charge stable, la forme est à l'équilibre.
    assert out["tsb"].iloc[-1] == pytest.approx(0.0, abs=0.2)


def test_atl_reacts_faster_than_ctl_to_a_load_spike():
    df = _daily([5.0] * 60 + [40.0] * 7, col="cardio_load_total")
    out = stats.ctl_atl_tsb(df)
    last = out.iloc[-1]
    assert last["atl"] > last["ctl"], "la fatigue doit monter plus vite que la forme de fond"
    assert last["tsb"] < 0, "une surcharge récente doit donner un TSB négatif"


def test_ctl_maturity_flags_an_immature_model():
    """39 jours d'historique ne suffisent pas à une moyenne exponentielle 42 j :
    la courbe existe mais ne doit pas être présentée comme fiable."""
    df = _daily([10.0] * 39, col="cardio_load_total")
    out = stats.ctl_atl_tsb(df)
    assert out["ctl_maturity"].iloc[-1] < 1.0
    assert out["atl_maturity"].iloc[-1] == pytest.approx(1.0)


def test_missing_days_count_as_zero_load():
    df = pd.DataFrame({
        "local_date": pd.to_datetime(["2026-01-01", "2026-01-10"]),
        "cardio_load_total": [10.0, 10.0],
    })
    out = stats.ctl_atl_tsb(df)
    assert len(out) == 10, "la grille doit être journalière et continue"
    assert out["cardio_load_total"].iloc[1:9].sum() == 0


def test_tsb_status_scales_with_ctl():
    assert stats.tsb_status(-5, 50)[0] in {"good", "serious"}
    assert stats.tsb_status(-30, 40)[0] == "critical"
    assert stats.tsb_status(10, 40)[0] == "excellent"
    assert stats.tsb_status(None, None)[0] == "neutral"


# --- Verdict du jour --------------------------------------------------------
def test_day_verdict_concedes_an_adverse_signal_instead_of_contradicting_itself():
    """Le cas qui a motivé la fonction : forme fraîche ET récupération basse.
    L'écran affichait « Frais » et « HRV en dessous » côte à côte sans trancher."""
    v = stats.day_verdict(8, 28, {"Récupération (HRV)": (-1.6, 1)})
    assert v.status == "excellent"
    assert v.headline.startswith("Frais, mais")
    assert "récupération" in v.headline
    assert [n[0] for n in v.nuances] == ["Récupération (HRV)"]


def test_day_verdict_tempers_its_recommendation_when_a_signal_is_adverse():
    """« Prêt pour un effort intense » sous « récupération en retrait » : le
    verdict tenait compte du signal, la recommandation non."""
    v = stats.day_verdict(8, 28, {"Récupération": (-1.6, 1)})
    assert v.hint == stats.TEMPERED_HINT
    assert "intense" not in v.hint


def test_day_verdict_keeps_the_conservative_hint_on_an_already_loaded_day():
    """Sur un statut déjà prudent, la consigne d'origine est plus stricte que
    la version tempérée : la remplacer relâcherait la contrainte."""
    v = stats.day_verdict(-20, 30, {"Récupération": (-2.0, 1)})
    assert v.status == "critical"
    assert v.hint == stats.TSB_BADGES["critical"][1]


def test_day_verdict_stays_simple_when_nothing_contradicts_the_form():
    v = stats.day_verdict(8, 28, {"Récupération (HRV)": (0.3, 1), "Sommeil": (-0.5, 1)})
    assert v.headline == "Frais"
    assert v.nuances == [], "sous 1 écart-type, il n'y a rien à dire"


def test_day_verdict_does_not_concede_a_favourable_signal():
    v = stats.day_verdict(8, 28, {"Récupération (HRV)": (2.2, 1)})
    assert v.headline == "Frais"
    assert v.nuances[0][2] == "excellent", "le signal reste listé, mais ne nuance pas"


def test_day_verdict_ranks_nuances_by_magnitude():
    v = stats.day_verdict(-15, 30, {
        "Sommeil": (-1.2, 1),
        "Fatigue récente": (2.8, -1),
        "Récupération (HRV)": (-0.4, 1),
    })
    assert [n[0] for n in v.nuances] == ["Fatigue récente", "Sommeil"]
    assert "fatigue récente nettement au-dessus" in v.headline


def test_day_verdict_ignores_signals_without_a_good_bad_direction():
    v = stats.day_verdict(8, 28, {"Charge du jour": (-3.0, 0)})
    assert v.nuances == []
    assert v.headline == "Frais"


def test_day_verdict_without_a_usable_model_says_so():
    v = stats.day_verdict(None, None, {"Récupération (HRV)": (-2.0, 1)})
    assert v.status == "neutral"
    assert v.headline.startswith("Indéterminé")
    assert v.nuances, "les signaux restent lisibles même sans modèle de forme"


# --- Verdict de progression -------------------------------------------------
def _trend(slope_per_day, n=40, noise=0.0, seed=0):
    """Tendance à pente CONNUE, calculée par `stats.trend` lui-même : les tests
    du verdict ne doivent tester que la composition, pas re-tester la régression."""
    rng = np.random.default_rng(seed)
    values = [100 + slope_per_day * i + rng.normal(0, noise) for i in range(n)]
    return stats.trend(_daily(values), "v")


def test_progress_verdict_reads_a_rising_metric_as_progress():
    v = stats.progress_verdict({"VO2max": (_trend(0.02), 1)}, primary="VO2max")
    assert v.headline == "Tu progresses"
    assert v.status == "good"
    assert v.nuances[0][2] == "good"


def test_progress_verdict_reads_direction_from_the_metric_not_the_sign():
    """FC de repos qui MONTE : la pente est positive, la nouvelle est mauvaise.
    C'est tout l'intérêt de passer la direction du registre."""
    v = stats.progress_verdict({"FC de repos": (_trend(0.05), -1)})
    assert v.headline == "En recul"
    assert v.status == "serious"
    assert v.nuances[0][2] == "serious"


def test_progress_verdict_never_calls_a_short_history_a_plateau():
    """« Plateau » est une affirmation ; sur cinq points, il n'y a rien à
    affirmer. C'est la distinction que fait déjà `Trend.label`."""
    v = stats.progress_verdict({"VO2max": (_trend(0.02, n=5), 1)})
    assert v.headline == "Pas encore concluant"
    assert v.status == "neutral"
    assert "pas assez de mesures" in v.nuances[0][1]
    # Pas de « (n=5) » en surface : l'effectif est dans le détail chiffré.
    assert "n=" not in v.nuances[0][1]


def test_progress_verdict_without_any_trend_at_all():
    v = stats.progress_verdict({"VO2max": (None, 1)})
    assert v.headline == "Pas encore concluant"
    assert v.nuances[0][3] != v.nuances[0][3], "pente NaN : rien à afficher comme valeur"


def test_progress_verdict_never_calls_an_inconclusive_slope_a_plateau():
    """Soixante points, une pente réelle nulle, du bruit : p est élevé. C'est
    précisément le cas où l'on est tenté d'écrire « Plateau » — et c'est un
    retournement d'une absence de preuve en preuve d'absence. Le verdict dit
    ce qu'il sait : rien de mesurable."""
    v = stats.progress_verdict({"VO2max": (_trend(0.0, n=60, noise=3.0), 1)})
    assert v.headline == "Rien de mesurable"
    assert v.status == "neutral"
    assert "plateau" in v.hint.lower(), "l'aide doit dire explicitement que ce n'en est pas un"


def test_merge_nuances_folds_identical_lines_into_one():
    """Trois lignes disant la même chose portent un seul bit d'information et
    occupent la place de trois signaux. Une fois le motif régulier, c'est sa
    RUPTURE qui devient le signal."""
    nuances = [
        ("VO2max", "aucune tendance nette", "neutral", 0.01),
        ("FC de repos", "aucune tendance nette", "neutral", 0.02),
        ("Variabilité cardiaque", "aucune tendance nette", "neutral", 0.03),
    ]
    merged = stats.merge_nuances(nuances, span_days=37)
    assert len(merged) == 1
    assert merged[0][0] == "VO2max, FC de repos et variabilité cardiaque"
    assert merged[0][1] == "aucune tendance nette sur 37 jours"
    # Sigle préservé au milieu de l'énumération.
    assert "fC de repos" not in merged[0][0]


def test_merge_nuances_keeps_anything_that_differs():
    """Deux pentes de valeurs différentes ont chacune quelque chose à dire :
    les fondre perdrait de l'information au lieu d'en gagner."""
    nuances = [
        ("VO2max", "hausse de +0.20 par semaine", "good", 0.2),
        ("FC de repos", "aucune tendance nette", "neutral", 0.0),
    ]
    assert len(stats.merge_nuances(nuances)) == 2


def test_progress_verdict_ranks_the_primary_metric_first_at_equal_status():
    """La VO2max arbitre le verdict ; la lister en dernier faisait dire à l'ordre
    le contraire de la règle de composition."""
    trends = {
        "FC de repos": (_trend(0.001, n=60, noise=3.0), -1),
        "Variabilité cardiaque": (_trend(0.001, n=60, noise=3.0, seed=2), 1),
        "VO2max": (_trend(0.001, n=60, noise=3.0, seed=3), 1),
    }
    v = stats.progress_verdict(trends, primary="VO2max")
    assert v.nuances[0][0] == "VO2max"


def test_progress_verdict_advice_follows_what_the_screen_actually_offers():
    """Le hint finissait par « Élargis l'horizon » alors que la page venait de
    retirer le sélecteur, faute d'historique : elle ôtait le contrôle et
    conseillait dans la même seconde de s'en servir."""
    trends = {"VO2max": (_trend(0.0, n=60, noise=3.0), 1)}
    widenable = stats.progress_verdict(trends, can_widen=True)
    stuck = stats.progress_verdict(trends, can_widen=False)
    assert widenable.headline == stuck.headline == "Rien de mesurable"
    assert "Élargis l'horizon" in widenable.hint
    assert "Élargis l'horizon" not in stuck.hint
    assert "quelques semaines" in stuck.hint


def test_progress_verdict_gives_no_advice_when_a_slope_concludes():
    """Une pente qui conclut n'appelle aucune action : le lecteur n'a qu'à la
    lire. Un conseil systématique serait du remplissage."""
    v = stats.progress_verdict({"VO2max": (_trend(0.02), 1)}, can_widen=False)
    assert v.headline == "Tu progresses"
    for action in stats.PROGRESS_ACTIONS.values():
        assert action not in v.hint


def test_progress_verdict_never_says_plateau_at_all():
    """Aucun chemin ne mène à cette affirmation : elle demanderait un test
    d'équivalence, donc une borne de non-pertinence par métrique."""
    assert not any("plateau" in headline.lower()
                   for headline, _status in stats.PROGRESS_BADGES.values())


def test_progress_verdict_lets_the_primary_metric_decide():
    trends = {
        "VO2max": (_trend(-0.02), 1),        # référence cardio : en baisse
        "HRV": (_trend(0.5), 1),             # secondaire : en hausse
    }
    assert stats.progress_verdict(trends, primary="VO2max").headline.startswith("En recul")
    # Sans métrique de référence, deux pentes CONCLUANTES de sens opposés : ce
    # n'est ni un progrès, ni un recul, ni un plateau — les deux signaux sont
    # réels, ils se contredisent.
    v = stats.progress_verdict(trends)
    assert v.headline == "Signaux contradictoires"
    assert v.status == "neutral"


def test_progress_verdict_concedes_an_adverse_metric():
    v = stats.progress_verdict(
        {"VO2max": (_trend(0.02), 1), "FC de repos": (_trend(0.05), -1)},
        primary="VO2max",
    )
    assert v.headline.startswith("Tu progresses, mais")
    # Sigle préservé : « fC de repos » serait une coquille visible à l'écran.
    assert "FC de repos va dans l'autre sens" in v.headline


def test_progress_verdict_ranks_adverse_metrics_first():
    v = stats.progress_verdict({
        "VO2max": (_trend(0.02), 1),
        "FC de repos": (_trend(0.05), -1),
        "Sommeil": (_trend(0.0, n=60, noise=30.0), 1),
    })
    assert [n[0] for n in v.nuances] == ["FC de repos", "VO2max", "Sommeil"]


def test_progress_verdict_ignores_metrics_without_a_good_bad_direction():
    v = stats.progress_verdict({"Charge": (_trend(0.5), 0)})
    assert v.nuances == []
    assert v.headline == "Pas encore concluant"


def test_progress_verdict_phrase_carries_the_unit():
    v = stats.progress_verdict(
        {"VO2max": (_trend(0.02), 1)}, units={"VO2max": " ml/kg/min"},
    )
    assert "ml/kg/min par semaine" in v.nuances[0][1]


# --- Libellés de surface vs détail chiffré ----------------------------------
def test_short_label_carries_no_statistical_apparatus():
    """La ligne que l'utilisateur lit en premier ne doit contenir ni effectif ni
    p-value : soit il sait ce qu'est un p, et le détail est à un clic ; soit il
    ne le sait pas, et le nombre ne fait que casser la phrase."""
    t = stats.trend(_daily([10 + 2 * i for i in range(30)]), "v")
    short = t.short_label(" u")
    assert short == "hausse de +14.00 u par semaine"
    assert "n=" not in short and "p=" not in short and "IC" not in short
    # Le détail, lui, garde tout.
    assert "n=30" in t.label() and "IC 95 %" in t.label()


def test_short_label_still_refuses_to_say_stable():
    rng = np.random.default_rng(0)
    t = stats.trend(_daily(rng.normal(50, 5, 60)), "v")
    assert t.short_label() == "aucune tendance nette"
    assert "stable" not in t.short_label()


def test_confidence_note_drops_the_count_and_falls_silent_when_ample():
    assert stats.confidence_note(5) == "trop peu pour conclure"
    assert stats.confidence_note(37) == "historique encore court"
    assert stats.confidence_note(200) == "", "aucune réserve à émettre : rien à dire"
    # La forme longue, elle, garde l'effectif pour le détail chiffré.
    assert "n=37" in stats.confidence_label(37)


# --- Sortie de zone normale -------------------------------------------------
#: Un plateau, puis une DÉRIVE — pas un décrochage en marche d'escalier.
#: Un décalage constant finit par entrer dans la médiane glissante et devient la
#: nouvelle normale au bout de 28 jours : c'est le comportement voulu d'une
#: baseline personnelle, et la fonction a raison de ne plus rien signaler. Le cas
#: qu'elle doit attraper est celui du fond de forme réel, où la série s'éloigne
#: plus vite que sa propre référence ne la suit.
def _drifting(slope_per_day: float, flat: int = 40, drift: int = 12):
    return [50.0] * flat + [50.0 + slope_per_day * i for i in range(1, drift + 1)]


def test_outside_band_since_dates_a_sustained_departure():
    """Le fait de la page « Progression » : la courbe passait sous sa zone
    normale sur tout le dernier tiers de la fenêtre, sans que rien le dise."""
    out = stats.outside_band_since(_daily(_drifting(-1.2)), "v")
    assert out is not None
    since, way = out
    assert way == -1
    # La date est le premier jour de la sortie EN COURS, pas la première de
    # l'historique : c'est « depuis quand », pas « déjà arrivé une fois ».
    assert since == pd.Timestamp("2026-02-10").date()


def test_outside_band_since_says_nothing_when_back_inside():
    assert stats.outside_band_since(_daily(_drifting(-1.2) + [50.0] * 3), "v") is None


def test_outside_band_since_ignores_a_one_day_excursion():
    """Une sortie d'un jour n'est que le bruit ordinaire d'une série contre sa
    propre dispersion."""
    assert stats.outside_band_since(_daily([50.0] * 40 + [20.0]), "v") is None


def test_outside_band_since_reports_the_upper_side_too():
    out = stats.outside_band_since(_daily(_drifting(1.2)), "v")
    assert out is not None and out[1] == 1


# --- Corrélations -----------------------------------------------------------
def test_corr_table_recovers_a_perfect_correlation():
    df = pd.DataFrame({"a": range(30), "b": [2 * i + 1 for i in range(30)], "c": [1] * 30})
    out = stats.corr_table(df, ["a", "b", "c"], min_n=10)
    ab = out[(out["a"] == "a") & (out["b"] == "b")].iloc[0]
    assert ab["r"] == pytest.approx(1.0)
    assert ab["is_significant"]
    # Une colonne constante n'a pas de corrélation définie.
    ac = out[(out["b"] == "c")].iloc[0]
    assert math.isnan(ac["r"])


def test_corr_table_suppresses_noise_across_many_tests():
    """Le vrai test : sur du bruit pur, croiser beaucoup de colonnes produit des
    corrélations "significatives" par hasard. La correction de Benjamini-Hochberg
    doit les éliminer."""
    rng = np.random.default_rng(42)
    df = pd.DataFrame({f"m{i}": rng.normal(size=39) for i in range(18)})
    out = stats.corr_table(df, list(df.columns), min_n=20)
    assert len(out) == 153, "18 métriques = 153 paires"
    naive = (out["p_value"] < 0.05).sum()
    corrected = out["is_significant"].sum()
    assert naive >= 3, "le test doit bien exhiber des faux positifs naïfs"
    assert corrected == 0, f"{corrected} fausse(s) découverte(s) ont survécu à la correction"


def test_corr_table_reports_n_below_threshold_without_crashing():
    df = pd.DataFrame({"a": [1, 2, 3], "b": [3, 2, 1]})
    out = stats.corr_table(df, ["a", "b"], min_n=20)
    assert math.isnan(out.iloc[0]["r"])
    assert out.iloc[0]["n"] == 3


def test_lagged_correlation_finds_the_right_lag():
    rng = np.random.default_rng(7)
    cause = rng.normal(size=60)
    df = pd.DataFrame({
        "local_date": pd.date_range("2026-01-01", periods=60, freq="D"),
        "charge": cause,
        # l'effet reproduit la cause avec 2 jours de retard
        "effet": np.concatenate([[np.nan, np.nan], cause[:-2]]),
    })
    out = stats.lagged_correlation(df, "charge", "effet", lags=range(0, 5))
    best = out.loc[out["r"].abs().idxmax()]
    assert best["lag_days"] == 2
    assert best["r"] == pytest.approx(1.0, abs=1e-6)


# --- Dette de sommeil -------------------------------------------------------
def test_sleep_debt_accumulates_against_the_real_goal():
    df = pd.DataFrame({
        "local_date": pd.date_range("2026-01-01", periods=5, freq="D"),
        "sleep_minutes_asleep": [400.0] * 5,
        "sleep_goal_minutes": [480.0] * 5,
    })
    out = stats.sleep_debt(df, window_days=14)
    assert out["deficit"].iloc[0] == pytest.approx(80.0)
    assert out["debt"].iloc[-1] == pytest.approx(400.0)


def test_sleep_debt_falls_back_to_default_goal():
    df = pd.DataFrame({
        "local_date": pd.date_range("2026-01-01", periods=3, freq="D"),
        "sleep_minutes_asleep": [420.0] * 3,
        "sleep_goal_minutes": [None] * 3,
    })
    out = stats.sleep_debt(df, default_goal=480.0)
    assert out["goal"].iloc[0] == pytest.approx(480.0)


# --- Fiabilité --------------------------------------------------------------
def test_confidence_label_is_explicit_about_small_samples():
    assert "trop peu" in stats.confidence_label(5)
    assert "indicative" in stats.confidence_label(20)
    assert "encore court" in stats.confidence_label(39)
    assert stats.confidence_label(200) == "n=200 jours"


# =============================================================================
# Règles déplacées depuis app/Bilan_du_jour.py
#
# Elles y étaient pures mais hors de portée des tests : une page Streamlit ne
# s'importe pas. Ce sont pourtant elles qui fixent les bornes de la réglette,
# le recul d'une tendance longue et le seuil d'une alerte.
# =============================================================================
def test_the_form_rail_axis_never_depends_on_the_day_being_shown():
    """LE point de la refonte : l'axe se recalculait à partir du TSB du jour,
    si bien qu'en naviguant d'un jour à l'autre le curseur se déplaçait alors
    que la forme n'avait pas bougé — et que le repère « il y a 7 jours » se
    retrouvait posé sur une règle qui n'était pas la sienne."""
    a = stats.tsb_rail_ranges(+18.0, 30.0)
    b = stats.tsb_rail_ranges(-25.0, 30.0)
    assert a == b, "deux jours de même fond doivent partager la même règle"
    assert a[0][0] == pytest.approx(-24.0) and a[-1][1] == pytest.approx(15.0)


def test_the_form_rail_always_offers_its_four_named_zones():
    """Une zone colorée mais sans nom laisse le lecteur chercher à quoi elle
    correspond. Les quatre paliers doivent exister et être assez larges pour
    porter leur libellé (seuil d'affichage de `charts.form_rail` : 12 %)."""
    ranges = stats.tsb_rail_ranges(0.0, 30.0)
    assert [r[2] for r in ranges] == list(stats.TSB_RAIL_STATUSES)
    span = ranges[-1][1] - ranges[0][0]
    assert min((hi - lo) / span for lo, hi, _ in ranges) >= 0.12


def test_the_form_rail_falls_back_on_a_fixed_scale_without_usable_ctl():
    for ctl in (None, 0.0, -5.0, float("nan")):
        ranges = stats.tsb_rail_ranges(0.0, ctl, fallback_good=(-10.0, 10.0))
        assert len(ranges) == 4
        assert ranges[0][0] < ranges[-1][1]


# --- tendance longue ---------------------------------------------------------
def _slow_frame(n: int, value: float = 50.0) -> pd.DataFrame:
    days = pd.date_range("2026-01-01", periods=n)
    return pd.DataFrame({"local_date": days, "vo2_max": [value] * n})


def test_long_term_reference_reports_the_lag_it_actually_achieved():
    """Un libellé « sur 3 mois » devant un écart calculé sur cinq semaines est
    un mensonge qu'aucun lecteur ne peut détecter."""
    df = _slow_frame(40)
    as_of = df["local_date"].iloc[-1].date()
    value, lag = stats.long_term_reference(df, "vo2_max", as_of, lag_days=90)
    assert value is not None
    assert lag < 90, "l'historique ne permet pas 90 jours"
    assert lag == 32


def test_long_term_reference_refuses_a_history_too_short_to_mean_anything():
    df = _slow_frame(20)
    as_of = df["local_date"].iloc[-1].date()
    assert stats.long_term_reference(df, "vo2_max", as_of)[0] is None


def test_long_term_reference_smooths_instead_of_comparing_two_lone_points():
    """Comparer deux points isolés d'une série bruitée fabrique une tendance à
    partir de deux accidents."""
    df = _slow_frame(200, 50.0)
    spike = len(df) - 100
    df.loc[spike, "vo2_max"] = 90.0   # un seul jour aberrant, pile sur la cible
    as_of = df["local_date"].iloc[-1].date()
    value, _ = stats.long_term_reference(df, "vo2_max", as_of, lag_days=100)
    assert value == pytest.approx(50.0), "la médiane doit absorber le point aberrant"


# --- dérive de la FC de repos ------------------------------------------------
def test_resting_hr_drift_uses_a_sliding_reference_that_never_dilutes():
    """La référence était « tout l'historique sauf les 5 derniers jours » : à
    39 jours cela comparait 5 jours à 34, dans un an cela en aurait comparé 5 à
    360. Une moyenne à vie ne bouge plus, et la règle se serait figée."""
    rng = np.random.default_rng(0)
    long_history = pd.Series(np.concatenate([
        rng.normal(50, 2, 700),          # un passé lointain sans rapport
        rng.normal(60, 2, 28),           # la référence récente
        np.full(5, 68.0),                # les cinq derniers jours
    ]))
    drift = stats.resting_hr_drift(long_history)
    assert drift is not None
    _, base, sigmas = drift
    assert base == pytest.approx(60, abs=1.5), "la référence doit être la fenêtre récente"
    assert sigmas > 1.5


def test_resting_hr_drift_is_expressed_in_robust_sigmas_not_beats():
    """Un « +3 bpm » codé en dur est un seuil pour quelqu'un dont la FC varie de
    3 bpm, et du bruit permanent pour quelqu'un dont elle varie de 6."""
    rng = np.random.default_rng(1)
    calm = pd.Series(np.concatenate([rng.normal(60, 1, 28), np.full(5, 63.0)]))
    noisy = pd.Series(np.concatenate([rng.normal(60, 6, 28), np.full(5, 63.0)]))
    assert stats.resting_hr_drift(calm)[2] > stats.resting_hr_drift(noisy)[2], (
        "le même écart en battements doit peser moins chez qui varie beaucoup"
    )


def test_resting_hr_drift_stays_silent_without_enough_nights():
    assert stats.resting_hr_drift(pd.Series([60.0] * 10)) is None
    assert stats.resting_hr_drift(pd.Series(dtype=float)) is None


def test_resting_hr_drift_stays_silent_on_a_perfectly_flat_reference():
    """MAD nul : tout écart vaudrait une infinité de sigmas."""
    assert stats.resting_hr_drift(pd.Series([60.0] * 28 + [70.0] * 5)) is None


# --- robust_z réutilisable ---------------------------------------------------
def test_robust_z_with_a_precomputed_baseline_matches_the_plain_call():
    """Le cache et la déduplication de calcul ne valent que si le résultat est
    strictement identique."""
    rng = np.random.default_rng(2)
    df = pd.DataFrame({"local_date": pd.date_range("2026-01-01", periods=60),
                       "v": rng.normal(50, 5, 60)})
    base = stats.rolling_baseline(df, "v")
    assert np.allclose(
        stats.robust_z(df, "v").to_numpy(),
        stats.robust_z(df, "v", baseline=base).to_numpy(),
        equal_nan=True,
    )
