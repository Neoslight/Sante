-- mart.weekly : agrégation ISO-semaine (lundi -> dimanche), avec deltas vs
-- semaine précédente. Dépend de mart.daily, mart.strength_sessions,
-- mart.strength_sets (donc exécuté après l'enrichissement Python).
--
-- Les jours partiels (premier jour de port, jour de l'export) sont exclus des
-- moyennes : comptés comme des jours pleins, ils tiraient chaque bord de série
-- vers le bas.

CREATE OR REPLACE TABLE mart.weekly AS
WITH daily_agg AS (
    SELECT
        date_trunc('week', local_date) AS week_start,
        count(*) AS days_in_week,
        count(*) FILTER (WHERE NOT is_partial_day AND NOT is_missing_day) AS days_complete,
        avg(steps) FILTER (WHERE NOT is_partial_day) AS avg_steps,
        avg(calories_total) FILTER (WHERE NOT is_partial_day) AS avg_calories_total,
        avg(kcal_zone_active) FILTER (WHERE NOT is_partial_day) AS avg_kcal_zone_active,
        avg(sedentary_min) FILTER (WHERE NOT is_partial_day) AS avg_sedentary_min,
        avg(sleep_minutes_asleep) AS avg_sleep_minutes_asleep,
        avg(sleep_score) AS avg_sleep_score,
        avg(resting_hr) AS avg_resting_hr,
        avg(hrv_rmssd) AS avg_hrv_rmssd,
        avg(readiness_score) AS avg_readiness_score,
        -- Interprétable depuis que le milieu de nuit est ancré à 18:00 et ne
        -- saute plus de 1440 min au passage de minuit.
        stddev_pop(sleep_midpoint_minutes) AS sleep_midpoint_stddev,
        avg(sleep_midpoint_minutes) AS avg_sleep_midpoint_minutes,
        sum(azm_points_total) AS azm_points_total,
        sum(cardio_load_total) AS cardio_load_total,
        sum(cardio_workouts_count) AS cardio_workouts_count
    FROM mart.daily
    GROUP BY 1
),
sessions_agg AS (
    SELECT date_trunc('week', local_date) AS week_start,
           count(*) AS strength_sessions_count,
           avg(rpe) AS avg_rpe
    FROM mart.strength_sessions
    GROUP BY 1
),
sets_agg AS (
    SELECT date_trunc('week', local_date) AS week_start,
           sum(duration_seconds) / 60.0 AS total_work_minutes,
           sum(duration_seconds) FILTER (WHERE muscle_group = 'jambes') / 60.0 AS jambes_min,
           sum(duration_seconds) FILTER (WHERE muscle_group = 'gainage') / 60.0 AS gainage_min,
           sum(duration_seconds) FILTER (WHERE muscle_group = 'haut_du_corps') / 60.0 AS haut_du_corps_min,
           sum(duration_seconds) FILTER (WHERE muscle_group = 'cou_epaules') / 60.0 AS cou_epaules_min,
           sum(duration_seconds) FILTER (WHERE muscle_group = 'cardio') / 60.0 AS cardio_min,
           sum(duration_seconds) FILTER (WHERE muscle_group = 'mobilite') / 60.0 AS mobilite_min,
           sum(duration_seconds) FILTER (WHERE muscle_group = 'autre') / 60.0 AS autre_min,
           -- nombre d'exécutions par groupe : unité complémentaire des minutes
           -- (un set de gainage et un set de squats ne se comparent pas en temps)
           count(*) AS total_work_segments,
           count(*) FILTER (WHERE muscle_group = 'jambes') AS jambes_segments,
           count(*) FILTER (WHERE muscle_group = 'gainage') AS gainage_segments,
           count(*) FILTER (WHERE muscle_group = 'haut_du_corps') AS haut_du_corps_segments,
           count(*) FILTER (WHERE muscle_group = 'cou_epaules') AS cou_epaules_segments,
           count(*) FILTER (WHERE muscle_group = 'cardio') AS cardio_segments,
           count(*) FILTER (WHERE muscle_group = 'mobilite') AS mobilite_segments,
           count(*) FILTER (WHERE muscle_group = 'autre') AS autre_segments,
           -- part du volume dont la durée a dû être reconstruite
           count(*) FILTER (WHERE duration_is_estimated) AS estimated_segments,
           count(*) FILTER (WHERE duration_seconds IS NULL) AS segments_without_duration
    FROM mart.strength_sets
    GROUP BY 1
)
SELECT
    d.week_start,
    d.week_start + INTERVAL 6 DAY AS week_end,
    d.days_in_week, d.days_complete,
    d.avg_steps, d.avg_calories_total, d.avg_kcal_zone_active, d.avg_sedentary_min,
    d.avg_sleep_minutes_asleep, d.avg_sleep_score, d.avg_resting_hr, d.avg_hrv_rmssd,
    d.avg_readiness_score,
    d.sleep_midpoint_stddev, d.avg_sleep_midpoint_minutes,
    d.azm_points_total, d.cardio_load_total,
    d.cardio_workouts_count,
    coalesce(s.strength_sessions_count, 0) AS strength_sessions_count,
    s.avg_rpe,
    st.total_work_minutes,
    st.jambes_min, st.gainage_min, st.haut_du_corps_min, st.cou_epaules_min, st.cardio_min, st.mobilite_min, st.autre_min,
    st.total_work_segments,
    st.jambes_segments, st.gainage_segments, st.haut_du_corps_segments, st.cou_epaules_segments,
    st.cardio_segments, st.mobilite_segments, st.autre_segments,
    st.estimated_segments, st.segments_without_duration,
    d.avg_steps - lag(d.avg_steps) OVER (ORDER BY d.week_start) AS avg_steps_delta,
    coalesce(s.strength_sessions_count, 0)
        - lag(coalesce(s.strength_sessions_count, 0)) OVER (ORDER BY d.week_start) AS strength_sessions_delta,
    d.avg_sleep_score - lag(d.avg_sleep_score) OVER (ORDER BY d.week_start) AS avg_sleep_score_delta,
    st.total_work_minutes - lag(st.total_work_minutes) OVER (ORDER BY d.week_start) AS total_work_minutes_delta
FROM daily_agg d
LEFT JOIN sessions_agg s USING (week_start)
LEFT JOIN sets_agg st USING (week_start)
ORDER BY d.week_start;
