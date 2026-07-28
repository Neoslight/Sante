"""Localisation des exports Takeout sur le disque.

Le dossier Google Takeout nomme son dossier racine "Google Health" avec une
espace insécable (U+00A0) entre les deux mots sur certains exports. On
résout ça avec un glob tolérant plutôt que de coder le nom en dur.
"""
from pathlib import Path

from .config import EXPORTS_DIR


def list_exports() -> list[Path]:
    """Retourne les dossiers d'export triés du plus ancien au plus récent."""
    if not EXPORTS_DIR.exists():
        return []
    return sorted(p for p in EXPORTS_DIR.iterdir() if p.is_dir())


def latest_export() -> Path | None:
    exports = list_exports()
    return exports[-1] if exports else None


def google_health_root(export_dir: Path) -> Path:
    """Trouve le dossier 'Google Health' (espace normale ou insécable) sous un export."""
    candidates = list(export_dir.glob("Google*Health")) + list(export_dir.glob("Google Health"))
    if not candidates:
        # peut-être directement à la racine, ou sous Takeout/
        candidates = list(export_dir.glob("**/Google*Health"))
    if not candidates:
        raise FileNotFoundError(f"Dossier 'Google Health' introuvable sous {export_dir}")
    return candidates[0]
