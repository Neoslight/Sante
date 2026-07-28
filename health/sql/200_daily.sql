-- mart.daily : une ligne par jour local (Europe/Paris), du premier jour de port
-- du Fitbit Air (device_start()) au dernier jour réellement couvert par les
-- données.
--
-- Points de vigilance traités ici :
--   * conversion locale via to_local() (cf. install_sql_context) : `AT TIME ZONE
--     'Europe/Paris'` seul était un aller-retour identité sur des timestamps
--     UTC naïfs, donc tous les "jours locaux" étaient en fait des jours UTC ;
--   * pas et distance : plusieurs appareils remontent la même métrique, on ne
--     retient qu'une source par jour (meta.source_priority) au lieu de sommer ;
--   * la colonne vertébrale s'arrête au dernier jour couvert, plus à
--     current_date : les jours sans données ne sont plus des zéros qui tirent
--     les moyennes vers le bas ;
--   * complétude : les jours de bord (premier port, jour de l'export) sont
--     partiels et signalés comme tels.

CREATE OR REPLACE TABLE mart.daily AS
WITH coverage AS (
    -- La montre est la seule source d'échantillons de FC : sa couverture
    -- définit ce qu'est un jour "observé".
    SELECT to_local_date(timestamp) AS local_date, count(*) AS hr_samples
    FROM raw.heart_rate
    WHERE timestamp IS NOT NULL
    GROUP BY 1
),
spine AS (
    SELECT CAST(unnest(generate_series(
        device_start(),
        (SELECT max(local_date) FROM coverage),
        INTERVAL 1 DAY
    )) AS DATE) AS local_date
),
-- --- Pas et distance : une seule source par jour ---------------------------
steps_src AS (
    SELECT to_local_date(s.timestamp) AS local_date, s.data_source,
           sum(try_cast(s.steps AS DOUBLE)) AS steps
    FROM raw.steps s WHERE s.timestamp IS NOT NULL GROUP BY 1, 2
),
steps_d AS (
    SELECT steps_src.local_date, steps_src.steps, steps_src.data_source AS steps_source
    FROM steps_src
    LEFT JOIN meta.source_priority p
           ON p.metric = 'steps' AND p.data_source = steps_src.data_source
    QUALIFY row_number() OVER (
        PARTITION BY steps_src.local_date ORDER BY coalesce(p.priority, 999), steps_src.steps DESC
    ) = 1
),
distance_src AS (
    SELECT to_local_date(d.timestamp) AS local_date, d.data_source,
           sum(try_cast(d.distance AS DOUBLE)) AS distance_m
    FROM raw.distance d WHERE d.timestamp IS NOT NULL GROUP BY 1, 2
),
distance_d AS (
    SELECT distance_src.local_date, distance_src.distance_m,
           distance_src.data_source AS distance_source
    FROM distance_src
    LEFT JOIN meta.source_priority p
           ON p.metric = 'distance' AND p.data_source = distance_src.data_source
    QUALIFY row_number() OVER (
        PARTITION BY distance_src.local_date
        ORDER BY coalesce(p.priority, 999), distance_src.distance_m DESC
    ) = 1
),
-- --- Énergie ---------------------------------------------------------------
calories_d AS (
    SELECT to_local_date(timestamp) AS local_date,
           sum(try_cast(calories AS DOUBLE)) AS calories_total
    FROM raw.calories WHERE timestamp IS NOT NULL GROUP BY 1
),
active_kcal_d AS (
    SELECT to_local_date(timestamp) AS local_date,
           sum(try_cast(kilocalories AS DOUBLE)) AS active_kcal
    FROM raw.active_energy_burned WHERE timestamp IS NOT NULL GROUP BY 1
),
-- Répartition de la dépense par zone de FC : filière aérobie vs glycolytique.
-- UNSPECIFIED = sous la zone légère (métabolisme de repos).
kcal_zone_d AS (
    SELECT to_local_date(timestamp) AS local_date,
           sum(try_cast(kcal AS DOUBLE)) FILTER (WHERE heart_rate_zone_type = 'LIGHT') AS kcal_zone_light,
           sum(try_cast(kcal AS DOUBLE)) FILTER (WHERE heart_rate_zone_type = 'MODERATE') AS kcal_zone_moderate,
           sum(try_cast(kcal AS DOUBLE)) FILTER (WHERE heart_rate_zone_type = 'VIGOROUS') AS kcal_zone_vigorous,
           sum(try_cast(kcal AS DOUBLE)) FILTER (WHERE heart_rate_zone_type = 'PEAK') AS kcal_zone_peak,
           sum(try_cast(kcal AS DOUBLE)) FILTER (
               WHERE heart_rate_zone_type = 'HEART_RATE_ZONE_TYPE_UNSPECIFIED') AS kcal_zone_rest
    FROM raw.calories_in_heart_rate_zone WHERE timestamp IS NOT NULL GROUP BY 1
),
-- --- Activité --------------------------------------------------------------
activity_level_d AS (
    SELECT to_local_date(timestamp) AS local_date,
           count(*) FILTER (WHERE level = 'SEDENTARY') AS sedentary_min,
           count(*) FILTER (WHERE level = 'LIGHTLY_ACTIVE') AS lightly_active_min,
           count(*) FILTER (WHERE level = 'MODERATELY_ACTIVE') AS moderately_active_min,
           count(*) FILTER (WHERE level = 'VERY_ACTIVE') AS very_active_min
    FROM raw.activity_level WHERE timestamp IS NOT NULL GROUP BY 1
),
-- ATTENTION : ce sont des POINTS AZM, pas des minutes. Fitbit compte 1 point
-- par minute en zone fat burn et 2 par minute en cardio/peak.
azm_d AS (
    SELECT to_local_date(timestamp) AS local_date,
           sum(try_cast(total_minutes AS DOUBLE)) FILTER (WHERE heart_rate_zone = 'FAT_BURN') AS azm_points_fat_burn,
           sum(try_cast(total_minutes AS DOUBLE)) FILTER (WHERE heart_rate_zone = 'CARDIO') AS azm_points_cardio,
           sum(try_cast(total_minutes AS DOUBLE)) FILTER (WHERE heart_rate_zone = 'PEAK') AS azm_points_peak
    FROM raw.active_zone_minutes WHERE timestamp IS NOT NULL GROUP BY 1
),
hr_zone_d AS (
    SELECT to_local_date(timestamp) AS local_date,
           count(*) FILTER (WHERE heart_rate_zone_type = 'LIGHT') AS hr_zone_light_min,
           count(*) FILTER (WHERE heart_rate_zone_type = 'MODERATE') AS hr_zone_moderate_min,
           count(*) FILTER (WHERE heart_rate_zone_type = 'VIGOROUS') AS hr_zone_vigorous_min,
           count(*) FILTER (WHERE heart_rate_zone_type = 'PEAK') AS hr_zone_peak_min
    FROM raw.time_in_heart_rate_zone WHERE timestamp IS NOT NULL GROUP BY 1
),
hr_d AS (
    SELECT to_local_date(timestamp) AS local_date,
           avg(try_cast(beats_per_minute AS DOUBLE)) AS hr_avg,
           min(try_cast(beats_per_minute AS DOUBLE)) AS hr_min,
           max(try_cast(beats_per_minute AS DOUBLE)) AS hr_max
    FROM raw.heart_rate WHERE timestamp IS NOT NULL GROUP BY 1
),
sedentary_d AS (
    SELECT to_local_date(start_time) AS local_date,
           sum(date_diff('second', start_time, end_time)) / 60.0 AS sedentary_period_min,
           max(date_diff('second', start_time, end_time)) / 60.0 AS longest_sedentary_period_min
    FROM raw.sedentary_period WHERE start_time IS NOT NULL GROUP BY 1
),
-- --- Métriques quotidiennes déjà agrégées par Fitbit -----------------------
rhr_d AS (
    SELECT CAST(timestamp AS DATE) AS local_date, try_cast(beats_per_minute AS DOUBLE) AS resting_hr
    FROM raw.daily_resting_heart_rate
),
hrv_d AS (
    SELECT CAST(timestamp AS DATE) AS local_date,
           try_cast(average_heart_rate_variability_milliseconds AS DOUBLE) AS hrv_rmssd,
           try_cast(deep_sleep_root_mean_square_of_successive_differences_milliseconds AS DOUBLE) AS hrv_deep_sleep_rmssd,
           try_cast(non_rem_heart_rate_beats_per_minute AS DOUBLE) AS non_rem_hr,
           try_cast(entropy AS DOUBLE) AS hrv_entropy
    FROM raw.daily_heart_rate_variability
),
resp_d AS (
    SELECT CAST(timestamp AS DATE) AS local_date, try_cast(breaths_per_minute AS DOUBLE) AS respiratory_rate
    FROM raw.daily_respiratory_rate
),
-- VO2max démographique (estimation cardio quotidienne, Global Export Data).
-- Même convention que les autres agrégats quotidiens Fitbit ci-dessus :
-- CAST(timestamp AS DATE) sans to_local_date(), la date est déjà locale.
vo2_max_d AS (
    SELECT CAST(timestamp AS DATE) AS local_date, try_cast(vo2_max AS DOUBLE) AS vo2_max
    FROM raw.vo2_max
),
readiness_d AS (
    SELECT CAST(timestamp AS DATE) AS local_date,
           try_cast(score AS DOUBLE) AS readiness_score,
           readiness_level,
           sleep_readiness, heart_rate_variability_readiness AS hrv_readiness,
           resting_heart_rate_readiness AS rhr_readiness
    FROM raw.daily_readiness
),
spo2_d AS (
    SELECT CAST(timestamp AS DATE) AS local_date,
           try_cast(average_percentage AS DOUBLE) AS spo2_avg,
           try_cast(lower_bound_percentage AS DOUBLE) AS spo2_lower,
           try_cast(upper_bound_percentage AS DOUBLE) AS spo2_upper,
           -- 0.0 sur les premiers jours = "pas encore de baseline", pas une
           -- saturation nulle.
           nullif(try_cast(baseline_percentage AS DOUBLE), 0) AS spo2_baseline
    FROM raw.daily_oxygen_saturation
),
skin_temp_d AS (
    SELECT CAST(timestamp AS DATE) AS local_date,
           try_cast(nightly_temperature_celsius AS DOUBLE) AS nightly_temp_c,
           try_cast(baseline_temperature_celsius AS DOUBLE) AS baseline_temp_c,
           try_cast(relative_nightly_stddev_30d_celsius AS DOUBLE) AS temp_stddev_30d_c
    FROM raw.daily_sleep_temperature_derivations
),
cardio_load_d AS (
    -- La série n'est PAS cumulative : chaque ligne est l'incrément de charge
    -- d'une minute (0,3 / 0,82 / 0,33...). L'ancien arg_max ne retenait donc
    -- que la dernière minute de la journée — d'où un "total" de 0,3 au lieu de
    -- 34. La somme redonne des valeurs cohérentes avec l'échelle personnelle
    -- observée dans raw.cardio_load_observed_interval (max 169,6).
    SELECT to_local_date(timestamp) AS local_date,
           sum(try_cast(workout AS DOUBLE)) AS cardio_load_workout,
           sum(try_cast(background AS DOUBLE)) AS cardio_load_background,
           sum(try_cast(total AS DOUBLE)) AS cardio_load_total
    FROM raw.cardio_load WHERE timestamp IS NOT NULL GROUP BY 1
),
acwr_d AS (
    SELECT CAST(timestamp AS DATE) AS local_date,
           try_cast(ratio AS DOUBLE) AS acwr_ratio,
           label AS acwr_label
    FROM raw.cardio_acute_chronic_workload_ratio
),
-- Fin de calibration des scores propriétaires Fitbit : avant cette date, le
-- readiness et la charge cardio ne sont pas fiables. Lu depuis la source plutôt
-- que codé en dur, pour rester juste au prochain export.
calibration AS (
    SELECT
        max(CAST(latest_completion_date AS DATE)) FILTER (
            WHERE feature = 'FEATURE_TYPE_READINESS') AS readiness_ready_on,
        max(CAST(latest_completion_date AS DATE)) FILTER (
            WHERE feature = 'FEATURE_TYPE_CARDIO_LOAD') AS cardio_load_ready_on
    FROM raw.calibration_status
),
-- Échelle personnelle observée de la charge cardio : c'est le dénominateur qui
-- rend une jauge de charge lisible (sinon "12,4" ne veut rien dire).
load_scale_d AS (
    SELECT CAST(timestamp AS DATE) AS local_date,
           try_cast(min_observed_load AS DOUBLE) AS cardio_load_min_observed,
           try_cast(max_observed_load AS DOUBLE) AS cardio_load_max_observed
    FROM raw.cardio_load_observed_interval
),
-- Les séances guidées du coach apparaissent AUSSI dans user_exercises en
-- "Structured Workout" : on sépare cardio et renfo pour ne plus les additionner
-- silencieusement avec mart.strength_sessions.
workouts_d AS (
    SELECT to_local_date(e.exercise_start) AS local_date,
           count(*) AS workouts_count,
           count(*) FILTER (WHERE r.activity_name IS NULL) AS cardio_workouts_count,
           count(*) FILTER (WHERE r.activity_name IS NOT NULL) AS renfo_workouts_count,
           sum(date_diff('second', e.exercise_start, e.exercise_end)) / 60.0 AS workout_minutes,
           sum(date_diff('second', e.exercise_start, e.exercise_end))
               FILTER (WHERE r.activity_name IS NULL) / 60.0 AS cardio_workout_minutes,
           sum(try_cast(e.tracker_total_calories AS DOUBLE)) AS workout_kcal
    FROM raw.user_exercises e
    LEFT JOIN meta.renfo_activity_names r ON r.activity_name = e.activity_name
    WHERE e.exercise_start IS NOT NULL
    GROUP BY 1
)
SELECT
    spine.local_date,
    -- Complétude : un jour sans échantillon de FC n'est pas un jour à zéro,
    -- c'est un jour non observé. Les jours de bord (premier port de la montre,
    -- jour de l'export) sont partiels et doivent être exclus des moyennes.
    coalesce(coverage.hr_samples, 0) AS hr_samples,
    coalesce(coverage.hr_samples, 0) / hr_samples_full_day() AS data_completeness,
    coverage.hr_samples IS NULL AS is_missing_day,
    coalesce(coverage.hr_samples, 0) < partial_day_threshold() * hr_samples_full_day()
        AS is_partial_day,
    -- Les scores propriétaires Fitbit ne sont pas fiables tant que l'appareil
    -- se calibre (cf. raw.calibration_status).
    spine.local_date <= cal.readiness_ready_on AS readiness_in_calibration,
    spine.local_date <= cal.cardio_load_ready_on AS cardio_load_in_calibration,

    -- Sur un jour observé, l'absence de pas signifie vraiment zéro pas ;
    -- sur un jour non observé, elle ne signifie rien.
    CASE WHEN coverage.hr_samples IS NOT NULL THEN coalesce(steps_d.steps, 0) END AS steps,
    steps_d.steps_source,
    distance_d.distance_m,
    distance_d.distance_source,
    calories_d.calories_total,
    active_kcal_d.active_kcal,
    kcal_zone_d.kcal_zone_rest,
    kcal_zone_d.kcal_zone_light,
    kcal_zone_d.kcal_zone_moderate,
    kcal_zone_d.kcal_zone_vigorous,
    kcal_zone_d.kcal_zone_peak,
    coalesce(kcal_zone_d.kcal_zone_moderate, 0)
        + coalesce(kcal_zone_d.kcal_zone_vigorous, 0)
        + coalesce(kcal_zone_d.kcal_zone_peak, 0) AS kcal_zone_active,

    activity_level_d.sedentary_min,
    activity_level_d.lightly_active_min,
    activity_level_d.moderately_active_min,
    activity_level_d.very_active_min,

    azm_d.azm_points_fat_burn,
    azm_d.azm_points_cardio,
    azm_d.azm_points_peak,
    coalesce(azm_d.azm_points_fat_burn, 0) + coalesce(azm_d.azm_points_cardio, 0)
        + coalesce(azm_d.azm_points_peak, 0) AS azm_points_total,

    hr_zone_d.hr_zone_light_min,
    hr_zone_d.hr_zone_moderate_min,
    hr_zone_d.hr_zone_vigorous_min,
    hr_zone_d.hr_zone_peak_min,
    hr_d.hr_avg, hr_d.hr_min, hr_d.hr_max,
    sedentary_d.sedentary_period_min,
    sedentary_d.longest_sedentary_period_min,
    rhr_d.resting_hr,
    hrv_d.hrv_rmssd, hrv_d.hrv_deep_sleep_rmssd, hrv_d.non_rem_hr, hrv_d.hrv_entropy,
    resp_d.respiratory_rate,
    vo2_max_d.vo2_max,
    readiness_d.readiness_score, readiness_d.readiness_level,
    readiness_d.sleep_readiness, readiness_d.hrv_readiness, readiness_d.rhr_readiness,
    spo2_d.spo2_avg, spo2_d.spo2_lower, spo2_d.spo2_upper, spo2_d.spo2_baseline,
    skin_temp_d.nightly_temp_c, skin_temp_d.baseline_temp_c, skin_temp_d.temp_stddev_30d_c,
    skin_temp_d.nightly_temp_c - skin_temp_d.baseline_temp_c AS skin_temp_deviation_c,
    cardio_load_d.cardio_load_workout, cardio_load_d.cardio_load_background, cardio_load_d.cardio_load_total,
    load_scale_d.cardio_load_min_observed, load_scale_d.cardio_load_max_observed,
    acwr_d.acwr_ratio, acwr_d.acwr_label,
    coalesce(workouts_d.workouts_count, 0) AS workouts_count,
    coalesce(workouts_d.cardio_workouts_count, 0) AS cardio_workouts_count,
    coalesce(workouts_d.renfo_workouts_count, 0) AS renfo_workouts_count,
    workouts_d.workout_minutes,
    workouts_d.cardio_workout_minutes,
    workouts_d.workout_kcal,
    -- nuit qui SE TERMINE ce jour-là (le réveil du matin même)
    sl.overall_score AS sleep_score,
    sl.minutes_asleep AS sleep_minutes_asleep,
    sl.total_sleep_minutes AS sleep_total_minutes,
    sl.nap_minutes AS sleep_nap_minutes,
    sl.sleep_goal_minutes,
    sl.efficiency_pct AS sleep_efficiency_pct,
    sl.deep_minutes AS sleep_deep_minutes,
    sl.rem_minutes AS sleep_rem_minutes,
    sl.light_minutes AS sleep_light_minutes,
    sl.awake_stage_minutes AS sleep_awake_minutes,
    sl.sleep_midpoint_minutes,
    sl.sleep_midpoint_local
FROM spine
CROSS JOIN calibration cal
LEFT JOIN coverage ON coverage.local_date = spine.local_date
LEFT JOIN steps_d ON steps_d.local_date = spine.local_date
LEFT JOIN distance_d ON distance_d.local_date = spine.local_date
LEFT JOIN calories_d ON calories_d.local_date = spine.local_date
LEFT JOIN active_kcal_d ON active_kcal_d.local_date = spine.local_date
LEFT JOIN kcal_zone_d ON kcal_zone_d.local_date = spine.local_date
LEFT JOIN activity_level_d ON activity_level_d.local_date = spine.local_date
LEFT JOIN azm_d ON azm_d.local_date = spine.local_date
LEFT JOIN hr_zone_d ON hr_zone_d.local_date = spine.local_date
LEFT JOIN hr_d ON hr_d.local_date = spine.local_date
LEFT JOIN sedentary_d ON sedentary_d.local_date = spine.local_date
LEFT JOIN rhr_d ON rhr_d.local_date = spine.local_date
LEFT JOIN hrv_d ON hrv_d.local_date = spine.local_date
LEFT JOIN resp_d ON resp_d.local_date = spine.local_date
LEFT JOIN vo2_max_d ON vo2_max_d.local_date = spine.local_date
LEFT JOIN readiness_d ON readiness_d.local_date = spine.local_date
LEFT JOIN spo2_d ON spo2_d.local_date = spine.local_date
LEFT JOIN skin_temp_d ON skin_temp_d.local_date = spine.local_date
LEFT JOIN cardio_load_d ON cardio_load_d.local_date = spine.local_date
LEFT JOIN load_scale_d ON load_scale_d.local_date = spine.local_date
LEFT JOIN acwr_d ON acwr_d.local_date = spine.local_date
LEFT JOIN workouts_d ON workouts_d.local_date = spine.local_date
LEFT JOIN mart.sleep sl ON sl.local_date = spine.local_date
ORDER BY spine.local_date;
