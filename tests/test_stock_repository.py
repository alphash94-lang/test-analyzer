from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.db.session import create_db_engine, create_session_factory
from app.models.stock import DartCorpCodeItem
from app.repositories.stock_repository import StockRepository
from app.services.stock_classification import classify_krx_stock
from app.utils.dates import now_kst
from tests.helpers import make_settings, migrate_database
from tests.test_stock_classification import minimum_item


def test_upsert_map_and_search_stock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "repository.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    repository = StockRepository()
    collected_at = now_kst()

    with sessions.begin() as session:
        upserted, review = repository.upsert_krx_records(
            session,
            [classify_krx_stock(minimum_item(name="검색검증"))],
            as_of_at=collected_at,
            collected_at=collected_at,
        )
        mapped = repository.apply_dart_codes(
            session,
            [
                DartCorpCodeItem(
                    corp_code="00123456",
                    corp_name="검색검증",
                    corp_eng_name="Search Check",
                    stock_code="000001",
                    modify_date=date(2026, 7, 29),
                )
            ],
            collected_at=collected_at,
        )

    with sessions() as session:
        by_name = repository.search(session, "검색")
        by_code = repository.search(session, "000001")

    assert upserted == 1
    assert review == 1
    assert mapped == 1
    assert by_name[0].symbol == "000001"
    assert by_code[0].dart_corp_code == "00123456"
    assert by_code[0].is_kospi is True
    assert by_code[0].dart_collected_at is not None
    assert by_code[0].dart_collected_at.utcoffset() is not None
    assert by_code[0].collected_at.utcoffset() is not None
    engine.dispose()
