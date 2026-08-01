from __future__ import annotations

import asyncio
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.db.models.market import MarketStatus, Stock
from app.db.session import create_db_engine, create_session_factory
from app.models.metadata import DataState
from app.providers.kind_market_status import KindMarketStatusProvider
from app.services.event_rules import corporate_event_screen
from app.services.market_status_service import MarketStatusService
from app.utils.dates import SEOUL
from tests.helpers import make_settings, migrate_database


def test_corporate_event_screen_is_conservative() -> None:
    assert corporate_event_screen(()) == "CLEAR"
    assert corporate_event_screen(("현금ㆍ현물배당결정",)) == "CLEAR"
    assert corporate_event_screen(("유상증자결정",)) == "REVIEW"
    assert corporate_event_screen(("[기재정정] 영업정지",)) == "REVIEW"
    assert corporate_event_screen(("회생절차개시신청",)) == "SEVERE"
    assert corporate_event_screen(("횡령ㆍ배임혐의발생",)) == "SEVERE"


def test_kind_provider_recognizes_clear_and_risk_responses() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        if request.url.path.endswith("/adminissue.do"):
            assert b"repIsuSrtCd=005930" in body
            return httpx.Response(
                200,
                text="<html><tbody><td>조회된 결과값이 없습니다.</td></tbody></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )
        if request.url.path.endswith("/tradinghaltissue.do"):
            return httpx.Response(
                200,
                text="<html><tbody><td>조회된 결과값이 없습니다.</td></tbody></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )
        return httpx.Response(
            200,
            text=(
                "<html><tbody><tr onclick=\"detailView('00593', "
                "'001234', '20260730000001','1')\"><td>삼성전자</td>"
                "</tr></tbody></html>"
            ),
            headers={"content-type": "text/html; charset=utf-8"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = KindMarketStatusProvider(make_settings(), client)
    try:
        management = asyncio.run(
            provider.fetch_management_issue(
                symbol="005930",
                stock_names=("삼성전자",),
            )
        )
        trading = asyncio.run(
            provider.fetch_trading_halt(
                symbol="005930",
                stock_names=("삼성전자",),
            )
        )
        delisting = asyncio.run(
            provider.fetch_delisting_review(symbol="005930")
        )
    finally:
        asyncio.run(client.aclose())

    assert management.state == DataState.AVAILABLE
    assert management.payload is False
    assert trading.payload is False
    assert delisting.payload is True


def test_market_status_service_persists_all_three_official_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "market-status.db", monkeypatch)
    settings = make_settings(
        database_url=database_url,
        raw_data_dir=tmp_path / "raw",
    )
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    collected_at = datetime(2026, 7, 30, 10, 0, tzinfo=SEOUL)
    with sessions.begin() as session:
        session.add(
            Stock(
                symbol="005930",
                name_ko="삼성전자보통주",
                abbreviated_name="삼성전자",
                source_provider="KRX",
                source_function="test",
                data_state="AVAILABLE",
                as_of_at=collected_at,
                collected_at=collected_at,
                data_timing="NOT_APPLICABLE",
            )
        )

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            text="<html><tbody><td>조회된 결과값이 없습니다.</td></tbody></html>",
            headers={"content-type": "text/html; charset=utf-8"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = KindMarketStatusProvider(settings, client)
    service = MarketStatusService(settings, provider=provider)
    try:
        summary = asyncio.run(
            service.refresh(
                symbol="005930",
                as_of_date=date(2026, 7, 30),
            )
        )
    finally:
        service.close()
        asyncio.run(client.aclose())

    with sessions() as session:
        rows = session.scalars(
            select(MarketStatus).order_by(MarketStatus.status_type)
        ).all()
    assert summary.state == DataState.AVAILABLE
    assert summary.statuses == {
        "MANAGEMENT_STATUS": "NORMAL",
        "TRADING_STATUS": "NORMAL",
        "DELISTING_RISK": "CLEAR",
    }
    assert {
        (row.status_type, row.status_value, row.source_provider)
        for row in rows
    } == {
        ("MANAGEMENT_STATUS", "NORMAL", "KIND"),
        ("TRADING_STATUS", "NORMAL", "KIND"),
        ("DELISTING_RISK", "CLEAR", "KIND"),
    }
    engine.dispose()
