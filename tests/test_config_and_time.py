from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.utils.dates import ensure_kst, now_kst
from tests.helpers import make_settings


def test_settings_default_to_sqlite_and_hide_secrets() -> None:
    settings = make_settings(krx_api_key="do-not-print")

    assert settings.database_url == "sqlite:///./data/kospi_analyzer.db"
    assert settings.timezone == "Asia/Seoul"
    assert "do-not-print" not in repr(settings)


def test_blank_env_file_values_do_not_override_safe_defaults(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_ENV=\nLOG_LEVEL=\nDATABASE_URL=\n",
        encoding="utf-8",
    )

    settings = make_settings(env_file=env_file)

    assert settings.app_env == "development"
    assert settings.log_level == "INFO"
    assert settings.database_url == "sqlite:///./data/kospi_analyzer.db"


def test_postgres_database_url_uses_installed_psycopg_driver() -> None:
    settings = make_settings(
        database_url="postgresql://user:password@example.com/app?sslmode=require"
    )

    assert settings.database_url == (
        "postgresql+psycopg://user:password@example.com/app?sslmode=require"
    )


def test_now_kst_is_timezone_aware() -> None:
    current = now_kst()

    assert current.tzinfo is not None
    assert current.utcoffset() is not None
    assert current.tzname() == "KST"


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ensure_kst(datetime(2026, 7, 28, 12, 0, 0))  # noqa: DTZ001
