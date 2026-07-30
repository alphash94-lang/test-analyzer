from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.config import get_settings
from app.db.models.market import Stock
from app.db.session import create_db_engine, create_session_factory
from app.services.event_watchlist_service import EventWatchlistService
from tests.helpers import migrate_database

SEOUL = ZoneInfo("Asia/Seoul")


def _stock(symbol: str, name: str, *, share_class: str = "COMMON") -> Stock:
    timestamp = datetime(2026, 7, 30, 9, 0, tzinfo=SEOUL)
    return Stock(
        symbol=symbol,
        name_ko=name,
        is_kospi=True,
        security_type="STOCK",
        share_class=share_class,
        listing_status="LISTED",
        universe_status="INCLUDED",
        quality_state="VALID",
        is_active=True,
        source_provider="KRX",
        source_function="test fixture",
        data_state="AVAILABLE",
        as_of_at=timestamp,
        collected_at=timestamp,
    )


def test_watchlist_persists_only_eligible_kospi_common_stocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate_database(tmp_path / "watchlist.db", monkeypatch)
    settings = get_settings()
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        session.add_all(
            [
                _stock("005930", "삼성전자"),
                _stock("000660", "SK하이닉스"),
                _stock("005935", "삼성전자우", share_class="PREFERRED"),
            ]
        )
    engine.dispose()

    service = EventWatchlistService(settings)
    try:
        assert service.add_symbols(["005930", "000660", "005930"]) == 2
        assert service.add_symbols(["005930"]) == 0
        assert service.symbols() == ["000660", "005930"]
        service.set_news_query(symbol="000660", news_query="하이닉스")
        sk_hynix = next(
            item for item in service.list_items() if item.symbol == "000660"
        )
        assert sk_hynix.news_query == "하이닉스"
        with pytest.raises(ValueError, match="2자 이상"):
            service.set_news_query(symbol="000660", news_query="하")
        service.set_news_query(symbol="000660", news_query=None)
        sk_hynix = next(
            item for item in service.list_items() if item.symbol == "000660"
        )
        assert sk_hynix.news_query is None
        with pytest.raises(ValueError, match="활성 KOSPI 보통주"):
            service.add_symbols(["005935"])
        assert service.remove_symbols(["005930"]) == 1
        assert service.symbols() == ["000660"]
    finally:
        service.close()
