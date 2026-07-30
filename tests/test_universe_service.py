from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.models.metadata import DataState
from app.services.universe_service import UniverseService
from app.utils.dates import now_kst
from tests.helpers import make_settings, migrate_database


def test_no_keys_keeps_universe_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "no-keys.db", monkeypatch)
    settings = make_settings(
        database_url=database_url,
        raw_data_dir=tmp_path / "raw",
    )
    service = UniverseService(settings)
    try:
        summary = asyncio.run(service.refresh(now_kst().date()))
        count = service.stock_count()
    finally:
        service.close()

    assert summary.state == DataState.NOT_CONFIGURED.value
    assert summary.stocks_upserted == 0
    assert count == 0
