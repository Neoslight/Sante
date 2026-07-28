-- mart.workouts : séances trackées au sens large (vélo, marche, structured
-- workout...) issues de raw.user_exercises.
--
-- `workout_kind` sépare cardio et renforcement : les séances guidées du coach
-- apparaissent ici ET dans mart.strength_sessions, elles étaient donc comptées
-- deux fois dès qu'on additionnait les deux tables.
CREATE OR REPLACE TABLE mart.workouts AS
SELECT
    e.exercise_id,
    to_local_date(e.exercise_start) AS local_date,
    to_local(e.exercise_start) AS start_local,
    to_local(e.exercise_end) AS end_local,
    date_diff('second', e.exercise_start, e.exercise_end) / 60.0 AS duration_min,
    e.activity_name,
    e.log_type,
    CASE WHEN r.activity_name IS NOT NULL THEN 'renfo' ELSE 'cardio' END AS workout_kind,
    try_cast(e.tracker_total_calories AS DOUBLE) AS calories,
    try_cast(e.tracker_total_steps AS DOUBLE) AS steps,
    try_cast(e.tracker_total_distance_mm AS DOUBLE) / 1000.0 AS distance_m,
    try_cast(e.tracker_avg_heart_rate AS DOUBLE) AS avg_hr,
    try_cast(e.tracker_peak_heart_rate AS DOUBLE) AS peak_hr,
    try_cast(e.tracker_avg_pace_mm_per_second AS DOUBLE) / 1000.0 AS avg_pace_m_per_s
FROM raw.user_exercises e
LEFT JOIN meta.renfo_activity_names r ON r.activity_name = e.activity_name
WHERE e.exercise_start IS NOT NULL
  AND to_local_date(e.exercise_start) >= device_start()
ORDER BY e.exercise_start;

-- mart.strength_sessions : séances guidées coach (renforcement/mobilité),
-- une ligne par occurrence (workout_name, interval_start).
CREATE OR REPLACE TABLE mart.strength_sessions AS
SELECT
    workout_name,
    to_local_date(interval_start) AS local_date,
    to_local(interval_start) AS start_local,
    to_local(interval_end) AS end_local,
    date_diff('second', interval_start, interval_end) / 60.0 AS duration_min,
    max(workout_summary_type) AS workout_type,
    max(workout_summary_source) AS source,
    max(try_cast(rate_perceived_exertion AS DOUBLE)) AS rpe,
    count(*) FILTER (WHERE segment_type = 'WORKOUT_SEGMENT_TYPE_WORK') AS work_segments,
    count(DISTINCT segment_name) FILTER (WHERE segment_type = 'WORKOUT_SEGMENT_TYPE_WORK') AS distinct_movements,
    count(DISTINCT round_name) AS rounds
FROM raw.workout_summaries
WHERE interval_start IS NOT NULL
GROUP BY workout_name, interval_start, interval_end
HAVING to_local_date(interval_start) >= device_start()
ORDER BY interval_start;
