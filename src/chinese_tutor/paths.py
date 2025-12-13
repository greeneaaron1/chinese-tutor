from __future__ import annotations

import os
from pathlib import Path

APP_DIRNAME = "chinese-tutor"
DB_FILENAME = "chinese_tutor.db"
ENV_DB_PATH = "CHINESE_TUTOR_DB_PATH"


def get_data_dir() -> Path:
    """Return the data directory, creating it if needed."""
    env_override = os.environ.get(ENV_DB_PATH)
    if env_override:
        override_path = Path(env_override).expanduser()
        return override_path.parent if override_path.suffix else override_path

    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        base = Path(xdg_data)
    else:
        base = Path.home() / f".{APP_DIRNAME}"
    data_dir = base.expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_db_path() -> Path:
    """Resolve the SQLite database path and ensure its directory exists."""
    env_override = os.environ.get(ENV_DB_PATH)
    if env_override:
        db_path = Path(env_override).expanduser()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return db_path

    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / DB_FILENAME
