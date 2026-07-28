"""Chemins et constantes du profil utilisateur."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
EXPORTS_DIR = DATA_DIR / "exports"
WAREHOUSE_DIR = DATA_DIR / "warehouse"
DB_PATH = WAREHOUSE_DIR / "health.duckdb"
MANUAL_DIR = DATA_DIR / "manual"
BODY_CSV = MANUAL_DIR / "body.csv"

SQL_DIR = Path(__file__).resolve().parent / "sql"
MOVEMENTS_YAML = Path(__file__).resolve().parent / "movements.yaml"

# Le Fitbit Air n'a été porté qu'à partir de cette date : les données
# antérieures (téléphone seul) sont exclues des marts analytiques.
DEVICE_START_DATE = "2026-06-17"

TIMEZONE = "Europe/Paris"

# Plusieurs appareils remontent simultanément les mêmes métriques (la montre et
# le téléphone comptent tous les deux les pas). Sommer les lignes sans filtrer
# double le total : on ne retient qu'UNE source par (jour, métrique), la
# première disponible dans cet ordre.
#
# La montre (Radiance) est prioritaire : ses pas et sa distance sont cohérents
# entre eux (~5 500 pas/j x 0,726 m de foulée ~= 3 970 m/j mesurés), alors que
# le comptage téléphone est plus élevé sans distance correspondante.
SOURCE_PRIORITY: dict[str, tuple[str, ...]] = {
    "steps": ("Radiance", "Phone Health Connect", "MobileTrack"),
    "distance": ("Radiance", "Fitbit App"),
}

# raw.user_exercises mélange cardio et renforcement : les séances guidées du
# coach y apparaissent aussi en "Structured Workout", donc elles étaient
# comptées deux fois (une fois dans workouts_count, une fois dans
# strength_sessions_count).
RENFO_ACTIVITY_NAMES: tuple[str, ...] = ("Structured Workout", "Strength training", "Stretching")

# Le score de sommeil Fitbit utilise -2 comme sentinelle "non calculé".
SLEEP_SCORE_SENTINEL = -2

# Nombre médian d'échantillons de fréquence cardiaque sur une journée pleine
# avec la montre portée en continu (~37 000). Sert à mesurer la complétude d'un
# jour et à repérer les journées partielles (premier jour de port, jour de
# l'export) qui fausseraient les moyennes.
HR_SAMPLES_FULL_DAY = 37000
PARTIAL_DAY_THRESHOLD = 0.8

# Profil : valeurs de REPLI, neutres et versionnées, lues seulement si rien de
# mieux n'est disponible.
#
# Le vrai profil vient de `raw.user_profile` (ingéré depuis Your Profile/
# Profile.csv), recoupé avec les dernières pesées — cf. `health/profile.py`.
# Ce dictionnaire n'existe que pour le cas où l'export n'a pas encore été
# ingéré, ou pour une base de test minimale.
#
# Il ne contient donc PLUS de valeurs réelles. Une date de naissance, un sexe,
# une taille et un poids sont des données de santé identifiantes : dans un
# fichier suivi par git, elles entrent dans l'historique du dépôt, d'où l'on ne
# les retire plus (forks, caches d'indexation). `PROFILE_FILE` permet de les
# tenir hors du dépôt sans perdre le repli.
PROFILE_FILE = DATA_DIR / "profile.json"

#: Valeurs par défaut, volontairement génériques. Elles ne servent qu'à ce que
#: les formules dépendant de l'âge ou du poids produisent un nombre plutôt que
#: de lever, en attendant une vraie source.
PROFILE_DEFAULTS = {
    "sex": "MALE",
    "birth_date": "1990-01-01",
    "height_cm": 175.0,
    "weight_kg": 70.0,
}


def _load_profile() -> dict:
    """Repli local (`data/profile.json`, hors dépôt) sinon valeurs génériques.

    Silencieux sur un fichier absent — c'est le cas NORMAL sur une installation
    neuve. Silencieux aussi sur un JSON illisible : un profil de repli qui fait
    échouer l'import du module empêcherait l'app de démarrer pour une valeur
    dont elle n'a, la plupart du temps, même pas besoin.
    """
    profile = dict(PROFILE_DEFAULTS)
    try:
        with open(PROFILE_FILE, encoding="utf-8") as fh:
            profile.update({k: v for k, v in json.load(fh).items() if v is not None})
    except (OSError, ValueError):
        pass
    return profile


PROFILE = _load_profile()
