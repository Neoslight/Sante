"""Invariants structurels des tables mart.* construites depuis l'export réel
de l'utilisateur (data/exports/2026-07-25). Ces tests documentent aussi les
comptages attendus : un futur export ne devrait que les faire croître."""
import datetime as dt

from health.config import DEVICE_START_DATE


def test_daily_covers_expected_range_with_no_gaps_or_duplicates(con):
    rows = con.execute("SELECT local_date FROM mart.daily ORDER BY local_date").fetchall()
    dates = [r[0] for r in rows]

    assert dates[0] == dt.date.fromisoformat(DEVICE_START_DATE)
    assert len(dates) == len(set(dates)), "mart.daily contient des dates en double"

    expected = [dates[0] + dt.timedelta(days=i) for i in range((dates[-1] - dates[0]).days + 1)]
    assert dates == expected, "mart.daily a un trou dans la série de dates"


def test_daily_has_no_pre_device_data(con):
    n = con.execute(
        "SELECT count(*) FROM mart.daily WHERE local_date < ?", [DEVICE_START_DATE]
    ).fetchone()[0]
    assert n == 0


def test_sleep_has_one_row_per_local_date(con):
    dupes = con.execute(
        "SELECT local_date, count(*) c FROM mart.sleep GROUP BY 1 HAVING c > 1"
    ).fetchall()
    assert dupes == [], f"nuits en double après dédoublonnage algorithm_version : {dupes}"


def test_sleep_main_night_is_never_replaced_by_a_nap(con):
    """Régression : le 2026-06-25 la nuit avait été remplacée par un sommeil de
    65 min et le 2026-07-05 par une sieste de 15h20 à 17h17, parce que la
    déduplication gardait le dernier enregistrement recalculé, pas le principal."""
    short = con.execute(
        "SELECT local_date, minutes_asleep FROM mart.sleep WHERE minutes_asleep < 180"
    ).fetchall()
    assert short == [], f"nuits principales anormalement courtes (sieste retenue ?) : {short}"

    nap_day = con.execute(
        "SELECT minutes_asleep, nap_minutes FROM mart.sleep WHERE local_date = DATE '2026-07-05'"
    ).fetchone()
    assert nap_day is not None
    assert nap_day[0] > 180, "la nuit du 2026-07-05 doit être la nuit, pas la sieste"
    assert nap_day[1] > 0, "la sieste du 2026-07-05 doit être comptée séparément"


def test_sleep_midpoint_is_continuous_across_midnight(con):
    """Ancré à minuit, le milieu de nuit sautait de ~1440 min dès qu'un coucher
    passait 00:00 : l'écart-type hebdomadaire sortait à 600+ min pour une
    dispersion réelle de l'ordre de 30 min. Ancré à 18:00, il reste continu."""
    worst = con.execute("SELECT max(sleep_midpoint_stddev) FROM mart.weekly").fetchone()[0]
    assert worst is not None
    assert worst < 180, f"écart-type du milieu de nuit invraisemblable ({worst:.0f} min)"


def test_local_dates_are_paris_not_utc(con):
    """`ts AT TIME ZONE 'Europe/Paris'` sur un timestamp UTC naïf est un
    aller-retour identité : toutes les heures "locales" étaient en fait UTC.
    La séance du 2026-06-23 a démarré à 12h00 heure de Paris (10h00 UTC)."""
    start = con.execute(
        "SELECT start_local FROM mart.strength_sessions "
        "WHERE local_date = DATE '2026-06-23' ORDER BY start_local LIMIT 1"
    ).fetchone()[0]
    assert start.hour == 12, f"heure locale attendue 12h (Paris), obtenue {start}"


def test_daily_uses_a_single_source_per_metric(con):
    """La montre et le téléphone remontent tous les deux pas et distance :
    les sommer doublait le total (11 570 m le 2026-06-17 = 677 + 10 894)."""
    rows = con.execute(
        "SELECT DISTINCT steps_source, distance_source FROM mart.daily "
        "WHERE steps_source IS NOT NULL"
    ).fetchall()
    assert all(s == "Radiance" and d == "Radiance" for s, d in rows), rows


def test_partial_days_are_flagged(con):
    """Premier jour de port (montre à 15h58) et jour de l'export sont partiels :
    comptés comme des jours pleins, ils tiraient chaque bord de série vers le bas."""
    flagged = {
        r[0].isoformat()
        for r in con.execute("SELECT local_date FROM mart.daily WHERE is_partial_day").fetchall()
    }
    assert "2026-06-17" in flagged
    assert "2026-07-25" in flagged


def test_cardio_load_is_summed_not_last_sample(con):
    """raw.cardio_load contient des incréments par minute, pas une série
    cumulative : l'ancien arg_max ne gardait que la dernière minute du jour
    (~0,3) au lieu du total (~34). L'échelle personnelle observée par Fitbit
    donne l'ordre de grandeur attendu."""
    row = con.execute(
        "SELECT max(cardio_load_total), max(cardio_load_max_observed) FROM mart.daily"
    ).fetchone()
    max_day, max_observed = row
    assert max_day > 20, f"charge cardio quotidienne max invraisemblablement basse ({max_day})"
    assert max_day <= max_observed * 1.05, (
        f"charge quotidienne ({max_day}) au-dessus du maximum observé par Fitbit ({max_observed})"
    )


def test_sleep_score_sentinels_are_nulled(con):
    """-2 = "non calculé" côté Fitbit, sur 76 lignes sur 76 : ces sous-scores
    ne doivent jamais apparaître comme des valeurs numériques."""
    n = con.execute(
        "SELECT count(*) FROM mart.sleep WHERE -2 IN (duration_score, composition_score, revitalization_score)"
    ).fetchone()[0]
    assert n == 0


def test_sleep_stage_minutes_are_consistent_with_stage_summary(con):
    # somme des stades (deep+rem+light) doit être proche de minutes_asleep
    # (tolérance pour l'arrondi à la minute / stades RESTLESS non comptés)
    row = con.execute(
        """
        SELECT count(*)
        FROM mart.sleep
        WHERE deep_minutes IS NOT NULL
          AND abs((deep_minutes + rem_minutes + light_minutes) - minutes_asleep) > 15
        """
    ).fetchone()
    assert row[0] == 0


def test_strength_sets_durations_are_plausible(con):
    row = con.execute(
        "SELECT min(duration_seconds), max(duration_seconds) FROM mart.strength_sets "
        "WHERE duration_seconds IS NOT NULL"
    ).fetchone()
    min_dur, max_dur = row
    assert min_dur > 0
    assert max_dur < 3600, "une répétition/segment de plus d'1h suggère un bug de parsing de date"


def test_strength_sets_keep_every_work_segment(con):
    """Une séance entière ("Routine Quotidien Renforcement Cou & Épaules") n'a
    aucun horodatage à la source : ses sets restent sans durée mais doivent
    rester comptés en nombre d'exécutions, sinon un groupe musculaire complet
    disparaît des graphes."""
    n_sets = con.execute("SELECT count(*) FROM mart.strength_sets").fetchone()[0]
    n_work = con.execute(
        "SELECT count(*) FROM raw.workout_summaries "
        "WHERE segment_type = 'WORKOUT_SEGMENT_TYPE_WORK' AND segment_name IS NOT NULL "
        "AND to_local_date(interval_start) >= device_start()"
    ).fetchone()[0]
    assert n_sets == n_work, f"{n_work - n_sets} segments de travail perdus"


def test_strength_set_durations_are_mostly_recovered(con):
    """La source ne renseigne segment_start que sur 54 des 172 sets : sans
    reconstruction, 69 % du volume n'a pas de durée et deux groupes musculaires
    sont NULL toutes les semaines."""
    total, with_duration = con.execute(
        "SELECT count(*), count(duration_seconds) FROM mart.strength_sets"
    ).fetchone()
    assert with_duration / total > 0.6, (
        f"seulement {with_duration}/{total} sets ont une durée exploitable"
    )


def test_strength_sets_muscle_groups_are_all_mapped(con):
    groups = {r[0] for r in con.execute("SELECT DISTINCT muscle_group FROM mart.strength_sets").fetchall()}
    allowed = {"jambes", "gainage", "haut_du_corps", "cou_epaules", "cardio", "mobilite", "autre"}
    assert groups <= allowed


def test_reference_row_counts_are_at_least_the_known_export(con):
    # Comptages observés lors de l'ingestion de l'export du 2026-07-25.
    # Un futur export doit ajouter des lignes, jamais en perdre.
    minimums = {
        "raw.heart_rate": 1_418_937,
        "raw.steps": 23_213,
        "raw.calories": 76_326,
        "raw.user_sleep_stages": 4_646,
        "raw.workout_summaries": 230,
        "raw.user_exercises": 64,
        "raw.vo2_max": 39,
        "raw.daily_heart_rate_zones": 54,
        "raw.activity_goals": 10,
        "raw.user_profile": 1,
        "raw.heart_rate_variability_intraday": 3_503,
        "raw.oxygen_saturation_intraday": 19_003,
    }
    for table, minimum in minimums.items():
        n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        assert n >= minimum, f"{table} a {n} lignes, attendu >= {minimum}"


def test_vo2_max_is_plausible(con):
    """VO2max démographique Fitbit (Global Export Data/demographic_vo2_max-*.json) :
    la progression observée sur l'export réel va d'environ 51,9 à 53,7."""
    row = con.execute(
        "SELECT count(vo2_max), min(vo2_max), max(vo2_max) FROM mart.daily"
    ).fetchone()
    n, lo, hi = row
    assert n >= 39, f"seulement {n} jours avec vo2_max, attendu >= 39"
    assert 30 < lo < hi < 70, f"vo2_max hors fourchette plausible : [{lo}, {hi}]"


def test_hr_zones_are_increasing_and_non_overlapping(con):
    """Les bornes LIGHT/MODERATE/VIGOROUS/PEAK ne doivent jamais se chevaucher :
    max_bpm d'une zone < min_bpm de la zone suivante, pour chaque jour."""
    rows = con.execute(
        """
        SELECT local_date, zone_order, min_bpm, max_bpm,
               lead(min_bpm) OVER (PARTITION BY local_date ORDER BY zone_order) AS next_min_bpm
        FROM mart.hr_zones
        """
    ).fetchall()
    assert rows, "mart.hr_zones est vide"
    for local_date, zone_order, min_bpm, max_bpm, next_min_bpm in rows:
        assert min_bpm is not None and max_bpm is not None, f"{local_date} zone {zone_order} : bornes NULL"
        assert min_bpm < max_bpm, f"{local_date} zone {zone_order} : min_bpm >= max_bpm"
        if next_min_bpm is not None:
            assert max_bpm < next_min_bpm, (
                f"{local_date} zone {zone_order} : chevauchement (max_bpm={max_bpm} >= "
                f"next min_bpm={next_min_bpm})"
            )


def test_goals_targets_are_positive(con):
    """Activity Goals.csv : chaque objectif (pas, calories, distance, étages,
    minutes actives, eau) doit avoir une cible strictement positive."""
    rows = con.execute("SELECT goal_type, frequency, target FROM mart.goals").fetchall()
    assert rows, "mart.goals est vide"
    for goal_type, frequency, target in rows:
        assert target is not None and target > 0, f"{goal_type}/{frequency} : cible non positive ({target})"

    steps_daily = con.execute(
        "SELECT target FROM mart.goals WHERE goal_type = 'STEPS_GOAL' AND frequency = 'DAILY'"
    ).fetchone()
    assert steps_daily is not None
    assert steps_daily[0] == 10000.0, "objectif de pas quotidien attendu 10 000 (Activity Goals.csv)"


def test_hrv_intraday_is_plausible(con):
    """RMSSD toutes les ~5 min pendant le sommeil (heart_rate_variability_2026-*.csv)."""
    row = con.execute(
        "SELECT count(*), min(rmssd_ms), max(rmssd_ms) FROM mart.hrv_intraday"
    ).fetchone()
    n, lo, hi = row
    assert n >= 3_503, f"seulement {n} échantillons HRV intraday, attendu >= 3503"
    assert 0 < lo <= hi < 300, f"rmssd_ms hors fourchette plausible : [{lo}, {hi}]"


def test_spo2_intraday_is_plausible(con):
    """SpO2 par minute (oxygen_saturation_2026-*.csv) : bornes documentées 0-100."""
    row = con.execute(
        "SELECT count(*), min(spo2_pct), max(spo2_pct) FROM mart.spo2_intraday"
    ).fetchone()
    n, lo, hi = row
    assert n >= 19_003, f"seulement {n} échantillons SpO2 intraday, attendu >= 19003"
    assert 0 <= lo <= hi <= 100, f"spo2_pct hors bornes documentées : [{lo}, {hi}]"


def test_weight_and_height_are_sane():
    import duckdb
    from health.config import DB_PATH

    c = duckdb.connect(str(DB_PATH), read_only=True)
    weight_kg = c.execute("SELECT try_cast(weight_grams AS DOUBLE) / 1000.0 FROM raw.weight").fetchone()[0]
    height_cm = c.execute("SELECT try_cast(height_millimeters AS DOUBLE) / 10.0 FROM raw.height").fetchone()[0]
    c.close()

    assert 40 < weight_kg < 150
    assert 140 < height_cm < 220
