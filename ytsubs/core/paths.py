from __future__ import annotations

import os
from pathlib import Path
import re


PROFILE_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,63})$")
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(os.environ.get("YTSUBS_PROJECT_ROOT", DEFAULT_PROJECT_ROOT)).expanduser().resolve()
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = PROJECT_ROOT / ".cache"
CONFIG_DIR = PROJECT_ROOT / ".config"
MODS_DIR = PROJECT_ROOT / "mods"


def ensure_project_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    MODS_DIR.mkdir(parents=True, exist_ok=True)


def normalize_profile_name(name: str) -> str:
    normalized = name.strip().lower()
    if not PROFILE_NAME_RE.fullmatch(normalized):
        raise ValueError("profile names must be 1-64 characters using only letters, numbers, '-' or '_'")
    return normalized


def get_active_profile() -> str:
    profile_file = CONFIG_DIR / "active_profile.txt"
    if profile_file.exists():
        try:
            return normalize_profile_name(profile_file.read_text(encoding="utf-8").strip() or "default")
        except (OSError, ValueError):
            pass
    return "default"


def set_active_profile(name: str) -> None:
    ensure_project_dirs()
    profile_file = CONFIG_DIR / "active_profile.txt"
    profile_file.write_text(normalize_profile_name(name), encoding="utf-8")


def db_path(profile: str = "default") -> Path:
    ensure_project_dirs()
    profile = normalize_profile_name(profile)
    filename = "ytsubs.sqlite3" if profile == "default" else f"ytsubs_{profile}.sqlite3"
    path = (DATA_DIR / filename).resolve()
    if path.parent != DATA_DIR.resolve():
        raise ValueError("profile database path must remain inside the data directory")
    return path
