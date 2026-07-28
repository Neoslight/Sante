"""Registre déclaratif des datasets ingérés depuis l'export Google Health.

Pour ajouter un dataset : ajouter une entrée à PHYSICAL_ACTIVITY, HEALTH_FITNESS
ou REFERENCE. Le nom de table `raw.<name>` est dérivé du champ `name`.

Champs :
  name           -> nom de la table dans le schéma `raw`
  folder         -> sous-dossier sous "Google Health/"
  pattern        -> glob (relatif au dossier) des fichiers à charger
  ts_cols        -> colonnes (après slugification) à parser en TIMESTAMP UTC
  fmt            -> "csv" (défaut) ou "json"
  json_value_map -> (JSON uniquement) mapping clé source -> nom de colonne,
                     pour les fichiers au format Fitbit [{"dateTime", "value": {...}}]

Datasets volontairement exclus (bruit ML ou faible valeur analytique pour les
objectifs renforcement/perte de graisse abdominale) : UserActivityProbabilities,
UserSensorCompressionToken, micro_motion, micro_stillness, live_pace,
body_temperature (intraday), respiratory_rate_sleep_summary, hydration_log,
nutrition_log, mindfulness_session, swim_lengths_data, CoachWorkouts
(catalogue, pas des données personnelles), Menstrual Health, Social*,
SURVEYS_*, Commerce_*.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Dataset:
    name: str
    folder: str
    pattern: str
    ts_cols: tuple[str, ...] = field(default_factory=tuple)
    fmt: str = "csv"
    json_value_map: dict[str, str] | None = None


# --- Physical Activity_GoogleData -------------------------------------------
_PA = "Physical Activity_GoogleData"

PHYSICAL_ACTIVITY: list[Dataset] = [
    Dataset("heart_rate", _PA, "heart_rate_20*.csv", ("timestamp",)),
    Dataset("steps", _PA, "steps_20*.csv", ("timestamp",)),
    Dataset("distance", _PA, "distance_20*.csv", ("timestamp",)),
    Dataset("calories", _PA, "calories_20*.csv", ("timestamp",)),
    Dataset("active_energy_burned", _PA, "active_energy_burned_20*.csv", ("timestamp",)),
    Dataset("activity_level", _PA, "activity_level_20*.csv", ("timestamp",)),
    Dataset("calories_in_heart_rate_zone", _PA, "calories_in_heart_rate_zone_20*.csv", ("timestamp",)),
    Dataset("active_zone_minutes", _PA, "active_zone_minutes_20*.csv", ("timestamp",)),
    Dataset("time_in_heart_rate_zone", _PA, "time_in_heart_rate_zone_20*.csv", ("timestamp",)),
    Dataset("sedentary_period", _PA, "sedentary_period_20*.csv", ("start_time", "end_time")),
    Dataset("cardio_load", _PA, "cardio_load_20*.csv", ("timestamp",)),
    Dataset("cardio_load_observed_interval", _PA, "cardio_load_observed_interval.csv", ("timestamp",)),
    Dataset("cardio_acute_chronic_workload_ratio", _PA, "cardio_acute_chronic_workload_ratio.csv", ("timestamp",)),
    Dataset("daily_resting_heart_rate", _PA, "daily_resting_heart_rate.csv", ("timestamp",)),
    Dataset("daily_heart_rate_variability", _PA, "daily_heart_rate_variability.csv", ("timestamp",)),
    Dataset("daily_respiratory_rate", _PA, "daily_respiratory_rate.csv", ("timestamp",)),
    Dataset("daily_readiness", _PA, "daily_readiness.csv", ("timestamp",)),
    Dataset("daily_oxygen_saturation", _PA, "daily_oxygen_saturation.csv", ("timestamp",)),
    Dataset("daily_sleep_temperature_derivations", _PA, "daily_sleep_temperature_derivations.csv", ("timestamp",)),
    Dataset("weight", _PA, "weight.csv", ("timestamp",)),
    Dataset("height", _PA, "height.csv", ("timestamp",)),
    # Bornes personnelles (bpm) des zones de FC, recalculées périodiquement par
    # Fitbit. "heart_rate_zone" est une chaîne pseudo-JSON à 4 objets concaténés
    # sans crochets englobants et aux clés d'énumération non quotées -> parsée
    # par regex dans mart.hr_zones (cf. health/sql/500_reference.sql), pas ici.
    Dataset("daily_heart_rate_zones", _PA, "daily_heart_rate_zones.csv", ("timestamp",)),
    # RMSSD toutes les ~5 min pendant le sommeil.
    Dataset("heart_rate_variability_intraday", _PA, "heart_rate_variability_2026-*.csv", ("timestamp",)),
    # SpO2 par minute (essentiellement nocturne, quelques échantillons diurnes).
    Dataset("oxygen_saturation_intraday", _PA, "oxygen_saturation_2026-*.csv", ("timestamp",)),
]

# --- Health Fitness Data_GoogleData -----------------------------------------
_HF = "Health Fitness Data_GoogleData"

HEALTH_FITNESS: list[Dataset] = [
    Dataset(
        "workout_summaries",
        _HF,
        "WorkoutSummariesAndRounds.csv",
        (
            "interval_start", "interval_end",
            "round_start", "round_end",
            "segment_start", "segment_end",
            "set_start", "set_end",
        ),
    ),
    Dataset("user_exercises", _HF, "UserExercises_20*.csv",
            ("exercise_start", "exercise_end", "exercise_created", "exercise_last_updated")),
    Dataset("user_sleeps", _HF, "UserSleeps_20*.csv", ("sleep_start", "sleep_end")),
    Dataset("user_sleep_stages", _HF, "UserSleepStages_20*.csv", ("sleep_stage_start", "sleep_stage_end")),
    Dataset("user_sleep_scores", _HF, "UserSleepScores_20*.csv", ("score_time",)),
    Dataset("weekly_fitness_plans", _HF, "WeeklyFitnessPlans.csv", ()),
    Dataset("goal_settings_history", _HF, "GoalSettingsHistory.csv",
            ("update_time", "progress_start_time", "progress_end_time")),
    Dataset("user_profile_data", _HF, "UserProfileData.csv", ("value_time",)),
    Dataset("user_demographic_data", _HF, "UserDemographicData.csv", ("value_time",)),
    Dataset("calibration_status", _HF, "CalibrationStatusForReadinessAndLoad.csv", ()),
]


# --- Autres dossiers racine (pas sous _PA ni _HF) ---------------------------
# Chacun de ces dossiers n'existe qu'une fois dans l'export ("Global Export
# Data", "Activity Goals", "Your Profile") : pas de préfixe partagé comme
# _PA/_HF, le `folder` est donc écrit en toutes lettres par dataset.
REFERENCE: list[Dataset] = [
    # VO2max démographique (estimation cardio quotidienne). Seul dataset au
    # format JSON de l'export -> nécessite le chargeur JSON de loaders.py.
    Dataset(
        "vo2_max",
        "Global Export Data",
        "demographic_vo2_max-*.json",
        ("timestamp",),
        fmt="json",
        json_value_map={
            "demographicVO2Max": "vo2_max",
            "demographicVO2MaxError": "vo2_max_error",
            "filteredDemographicVO2Max": "vo2_max_filtered",
            "filteredDemographicVO2MaxError": "vo2_max_filtered_error",
        },
    ),
    Dataset("activity_goals", "Activity Goals", "Activity Goals.csv", ("created_on", "edited_on")),
    Dataset("user_profile", "Your Profile", "Profile.csv", ()),
]

ALL_DATASETS: list[Dataset] = PHYSICAL_ACTIVITY + HEALTH_FITNESS + REFERENCE
