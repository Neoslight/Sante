-- mart.sleep : une ligne par nuit, enrichie des scores et des stades.
--
-- Trois problèmes traités ici, dans cet ordre :
--   1. Fitbit réanalyse une même nuit sous un NOUVEAU sleep_id (changement de
--      version d'algorithme) au lieu de mettre à jour l'ancien. 37 des 38 nuits
--      existent donc en double, avec des durées légèrement différentes
--      (ex. 441 vs 495 min). On regroupe par CHEVAUCHEMENT d'intervalle et on
--      ne garde que la version la plus récemment recalculée.
--   2. Une fois les doublons résolus, il reste de vraies siestes (2026-06-26 et
--      2026-07-05). L'ancien `QUALIFY ... ORDER BY sleep_last_updated` en
--      gardait une au hasard, donc une sieste de 65 min pouvait REMPLACER la
--      nuit. On distingue explicitement nuit principale (la plus longue du
--      jour) et siestes (agrégées dans nap_minutes).
--   3. Le milieu de nuit était compté en minutes depuis minuit local, donc
--      sautait de ~1440 dès qu'un coucher passait 00:00 : l'écart-type
--      "régularité" sortait à 600+ min pour une dispersion réelle de ~30 min.
--      On ancre désormais à 18:00.

CREATE OR REPLACE TABLE mart.sleep AS
WITH stages AS (
    SELECT
        sleep_id,
        sum(CASE WHEN sleep_stage_type = 'DEEP' THEN
            date_diff('second', sleep_stage_start, sleep_stage_end) END) / 60.0 AS deep_minutes,
        sum(CASE WHEN sleep_stage_type = 'REM' THEN
            date_diff('second', sleep_stage_start, sleep_stage_end) END) / 60.0 AS rem_minutes,
        sum(CASE WHEN sleep_stage_type IN ('LIGHT', 'ASLEEP') THEN
            date_diff('second', sleep_stage_start, sleep_stage_end) END) / 60.0 AS light_minutes,
        sum(CASE WHEN sleep_stage_type IN ('AWAKE', 'RESTLESS') THEN
            date_diff('second', sleep_stage_start, sleep_stage_end) END) / 60.0 AS awake_stage_minutes
    FROM raw.user_sleep_stages
    GROUP BY 1
),
base AS (
    SELECT
        sleep_id, sleep_type, data_source,
        sleep_start, sleep_end, sleep_last_updated,
        try_cast(minutes_in_sleep_period AS DOUBLE) AS minutes_in_sleep_period,
        try_cast(minutes_asleep AS DOUBLE) AS minutes_asleep,
        try_cast(minutes_awake AS DOUBLE) AS minutes_awake,
        try_cast(minutes_to_fall_asleep AS DOUBLE) AS minutes_to_fall_asleep,
        try_cast(minutes_after_wake_up AS DOUBLE) AS minutes_after_wake_up,
        try_cast(minutes_longest_awakening AS DOUBLE) AS minutes_longest_awakening
    FROM raw.user_sleeps
    WHERE sleep_start IS NOT NULL AND sleep_end IS NOT NULL
),
-- 1. Regroupement par chevauchement : deux enregistrements qui se recouvrent
--    décrivent le même épisode de sommeil réel.
flagged AS (
    SELECT *,
        CASE WHEN sleep_start < max(sleep_end) OVER (
                 ORDER BY sleep_start ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
             THEN 0 ELSE 1 END AS is_new_episode
    FROM base
),
episodes AS (
    SELECT *, sum(is_new_episode) OVER (ORDER BY sleep_start ROWS UNBOUNDED PRECEDING) AS episode_id
    FROM flagged
),
-- Une ligne par épisode réel : la réanalyse la plus récente fait foi.
deduped AS (
    SELECT * FROM episodes
    QUALIFY row_number() OVER (
        PARTITION BY episode_id
        ORDER BY sleep_last_updated DESC, minutes_in_sleep_period DESC
    ) = 1
),
-- 2. Nuit principale (la plus longue du jour de réveil) vs siestes.
ranked AS (
    SELECT *,
        to_local_date(sleep_end) AS local_date,
        row_number() OVER (
            PARTITION BY to_local_date(sleep_end)
            ORDER BY minutes_asleep DESC, minutes_in_sleep_period DESC
        ) AS rn
    FROM deduped
),
naps AS (
    SELECT local_date,
           count(*) AS nap_count,
           sum(minutes_asleep) AS nap_minutes
    FROM ranked WHERE rn > 1 GROUP BY 1
)
SELECT
    m.sleep_id,
    m.sleep_type,
    m.data_source,
    to_local_date(m.sleep_start) AS sleep_start_date,
    m.local_date,
    to_local(m.sleep_start) AS sleep_start_local,
    to_local(m.sleep_end) AS sleep_end_local,
    -- Milieu de nuit, ancré à 18:00 pour rester continu autour de minuit.
    -- 0 = 18:00, 360 = minuit, 540 = 03:00.
    to_local(m.sleep_start) + INTERVAL 1 SECOND * (date_diff('second', m.sleep_start, m.sleep_end) / 2)
        AS sleep_midpoint_local,
    (
        (date_diff('minute', date_trunc('day', to_local(m.sleep_start)), to_local(m.sleep_start))
            + date_diff('second', m.sleep_start, m.sleep_end) / 120.0
            - 1080) % 1440 + 1440
    ) % 1440 AS sleep_midpoint_minutes,
    m.minutes_in_sleep_period,
    m.minutes_asleep,
    m.minutes_awake,
    m.minutes_to_fall_asleep,
    m.minutes_after_wake_up,
    m.minutes_longest_awakening,
    coalesce(n.nap_minutes, 0) AS nap_minutes,
    coalesce(n.nap_count, 0) AS nap_count,
    m.minutes_asleep + coalesce(n.nap_minutes, 0) AS total_sleep_minutes,
    CASE WHEN m.minutes_in_sleep_period > 0
        THEN 100.0 * m.minutes_asleep / m.minutes_in_sleep_period
    END AS efficiency_pct,
    try_cast(sc.overall_score AS DOUBLE) AS overall_score,
    -- -2 = sentinelle "non calculé" côté Fitbit (vrai sur 76 lignes sur 76 pour
    -- ces trois sous-scores : ils sont donc toujours NULL, pas des zéros).
    nullif(try_cast(sc.duration_score AS DOUBLE), -2) AS duration_score,
    nullif(try_cast(sc.composition_score AS DOUBLE), -2) AS composition_score,
    nullif(try_cast(sc.revitalization_score AS DOUBLE), -2) AS revitalization_score,
    try_cast(sc.resting_heart_rate AS DOUBLE) AS resting_heart_rate,
    try_cast(sc.rem_sleep_percent AS DOUBLE) AS rem_sleep_percent,
    try_cast(sc.deep_sleep_minutes AS DOUBLE) AS score_deep_sleep_minutes,
    try_cast(sc.sleep_goal_minutes AS DOUBLE) AS sleep_goal_minutes,
    try_cast(sc.restlessness_normalized AS DOUBLE) AS restlessness_normalized,
    try_cast(sc.waso_count_all_wake_time AS DOUBLE) AS waso_count_all_wake_time,
    try_cast(sc.waso_count_long_wakes AS DOUBLE) AS waso_count_long_wakes,
    st.deep_minutes,
    st.rem_minutes,
    st.light_minutes,
    st.awake_stage_minutes
FROM ranked m
LEFT JOIN naps n USING (local_date)
LEFT JOIN raw.user_sleep_scores sc ON sc.sleep_id = m.sleep_id
LEFT JOIN stages st ON st.sleep_id = m.sleep_id
WHERE m.rn = 1
  AND m.local_date >= device_start()
ORDER BY m.local_date;
