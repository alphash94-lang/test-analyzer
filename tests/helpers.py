from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from alembic import command
from alembic.config import Config

from app.config import Settings, get_settings


def make_settings(
    *,
    env_file: Path | str | None = None,
    **overrides: object,
) -> Settings:
    settings_factory = cast(Callable[..., Settings], Settings)
    return settings_factory(_env_file=env_file, **overrides)


def migrate_database(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    return database_url
