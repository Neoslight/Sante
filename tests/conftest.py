import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb
import pytest

from health.config import DB_PATH


@pytest.fixture(scope="module")
def con():
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    yield connection
    connection.close()


RAW_TABLES = [
    "heart_rate", "steps", "distance", "calories", "active_energy_burned",
    "activity_level", "calories_in_heart_rate_zone", "active_zone_minutes",
    "time_in_heart_rate_zone", "sedentary_period", "cardio_load",
    "cardio_load_observed_interval", "cardio_acute_chronic_workload_ratio",
    "daily_resting_heart_rate", "daily_heart_rate_variability",
    "daily_respiratory_rate", "daily_readiness", "daily_oxygen_saturation",
    "daily_sleep_temperature_derivations", "weight", "height",
    "workout_summaries", "user_exercises", "user_sleeps", "user_sleep_stages",
    "user_sleep_scores", "weekly_fitness_plans", "goal_settings_history",
    "user_profile_data", "user_demographic_data", "calibration_status",
    "vo2_max", "activity_goals", "user_profile",
    "daily_heart_rate_zones", "heart_rate_variability_intraday",
    "oxygen_saturation_intraday",
]
