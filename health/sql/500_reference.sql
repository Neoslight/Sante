-- Marts de référence / intraday, indépendants de mart.daily et de
-- mart.strength_sets : bandes de zones de FC, objectifs d'activité, et séries
-- intraday HRV/SpO2 utilisées pour les graphes détaillés (pas des agrégats
-- quotidiens). Exécuté après la phase ">= 400" par rebuild_marts (nom de
-- fichier trié après "400_..."), sans dépendance particulière sur cet ordre.

-- --- mart.hr_zones -----------------------------------------------------
-- Bornes personnelles (bpm) des zones de FC Fitbit, une ligne par jour x
-- zone. Sert à tracer les bandes de zones sur les graphes de FC.
--
-- raw.daily_heart_rate_zones stocke les 4 zones concaténées dans une seule
-- chaîne pseudo-JSON, sans crochets englobants et avec des clés d'énumération
-- non quotées :
--   {"heart_rate_zone_type": LIGHT, "min_heart_rate_bpm": 30, "max_heart_rate_bpm": 109},{...}
-- Ce n'est pas du JSON valide (LIGHT n'est pas une chaîne quotée) : on extrait
-- chaque zone par regex plutôt que de tenter un parse JSON.
CREATE OR REPLACE TABLE mart.hr_zones AS
WITH zone_names AS (
    SELECT * FROM (VALUES ('LIGHT', 1), ('MODERATE', 2), ('VIGOROUS', 3), ('PEAK', 4))
        AS t(heart_rate_zone_type, zone_order)
)
SELECT
    to_local_date(z.timestamp) AS local_date,
    zn.heart_rate_zone_type,
    zn.zone_order,
    try_cast(regexp_extract(
        z.heart_rate_zone,
        '"heart_rate_zone_type":\s*' || zn.heart_rate_zone_type
            || ',\s*"min_heart_rate_bpm":\s*(\d+),\s*"max_heart_rate_bpm":\s*(\d+)',
        1
    ) AS INTEGER) AS min_bpm,
    try_cast(regexp_extract(
        z.heart_rate_zone,
        '"heart_rate_zone_type":\s*' || zn.heart_rate_zone_type
            || ',\s*"min_heart_rate_bpm":\s*(\d+),\s*"max_heart_rate_bpm":\s*(\d+)',
        2
    ) AS INTEGER) AS max_bpm,
    z.data_source
FROM raw.daily_heart_rate_zones z
CROSS JOIN zone_names zn
WHERE z.timestamp IS NOT NULL
ORDER BY local_date, zone_order;

-- --- mart.goals ----------------------------------------------------------
-- Historique des objectifs d'activité Fitbit (pas, calories, distance,
-- étages, minutes actives, eau), quotidiens et hebdomadaires. Une ligne par
-- objectif défini sur une période [start_date, end_date]. Remplace le
-- 10 000 pas codé en dur dans app/pages/3_Depense_energetique.py.
CREATE OR REPLACE TABLE mart.goals AS
SELECT
    type AS goal_type,
    frequency,
    try_cast(target AS DOUBLE) AS target,
    try_cast(result AS DOUBLE) AS result,
    status,
    try_cast(is_primary AS BOOLEAN) AS is_primary,
    try_cast(start_date AS DATE) AS start_date,
    try_cast(end_date AS DATE) AS end_date,
    created_on,
    edited_on
FROM raw.activity_goals
ORDER BY goal_type, frequency, start_date;

-- --- mart.hrv_intraday -----------------------------------------------------
-- RMSSD toutes les ~5 min, essentiellement pendant le sommeil. `local_date`
-- suit la même convention que mart.sleep : la nuit est rattachée au jour où
-- elle SE TERMINE (le réveil, via to_local_date), pas au jour calendaire du
-- coucher.
CREATE OR REPLACE TABLE mart.hrv_intraday AS
SELECT
    to_local_date(timestamp) AS local_date,
    to_local(timestamp) AS timestamp_local,
    try_cast(root_mean_square_of_successive_differences_milliseconds AS DOUBLE) AS rmssd_ms,
    try_cast(standard_deviation_milliseconds AS DOUBLE) AS hrv_stddev_ms,
    data_source
FROM raw.heart_rate_variability_intraday
WHERE timestamp IS NOT NULL
ORDER BY timestamp_local;

-- --- mart.spo2_intraday ------------------------------------------------
-- SpO2 par minute (essentiellement nocturne, quelques échantillons diurnes
-- éparses). Même convention de date locale que hrv_intraday.
CREATE OR REPLACE TABLE mart.spo2_intraday AS
SELECT
    to_local_date(timestamp) AS local_date,
    to_local(timestamp) AS timestamp_local,
    try_cast(oxygen_saturation_percentage AS DOUBLE) AS spo2_pct,
    data_source
FROM raw.oxygen_saturation_intraday
WHERE timestamp IS NOT NULL
ORDER BY timestamp_local;
