from __future__ import annotations

import asyncio
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.db.models.market import Stock, StockClassification
from app.db.session import create_db_engine, create_session_factory
from app.models.metadata import DataState
from app.providers.kis_reference import KisReferenceProvider
from app.repositories.phase2_input_repository import Phase2InputRepository
from app.repositories.valuation_repository import ValuationRepository
from app.services.valuation_data_service import ValuationDataService
from app.utils.dates import SEOUL
from tests.helpers import make_settings, migrate_database


def test_kis_current_valuation_parses_official_per_and_pbr() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(
                200,
                json={"access_token": "token", "expires_in": 3600},
            )
        assert request.url.path.endswith("/quotations/inquire-price")
        assert request.url.params["FID_INPUT_ISCD"] == "005930"
        return httpx.Response(
            200,
            json={
                "rt_cd": "0",
                "msg_cd": "MCA00000",
                "msg1": "정상처리 되었습니다.",
                "output": {
                    "stck_prpr": "100000",
                    "prdy_vrss": "1500",
                    "prdy_ctrt": "1.52",
                    "stck_oprc": "99000",
                    "stck_hgpr": "101000",
                    "stck_lwpr": "98500",
                    "acml_vol": "1234567",
                    "acml_tr_pbmn": "123456700000",
                    "per": "12.34",
                    "pbr": "1.56",
                    "eps": "8103",
                    "bps": "64103",
                    "bstp_kor_isnm": "전기전자",
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = KisReferenceProvider(
        make_settings(kis_app_key="key", kis_app_secret="secret"),
        client,
    )
    try:
        response = asyncio.run(provider.fetch_current_valuation(symbol="005930"))
    finally:
        asyncio.run(client.aclose())

    assert response.state == DataState.AVAILABLE
    assert response.payload is not None
    assert response.payload[0].per == Decimal("12.34")
    assert response.payload[0].pbr == Decimal("1.56")
    assert response.payload[0].industry_name == "전기전자"
    assert response.payload[0].previous_day_change == Decimal(1500)
    assert response.payload[0].change_rate == Decimal("1.52")
    assert response.payload[0].open_price == Decimal(99000)
    assert response.payload[0].high_price == Decimal(101000)
    assert response.payload[0].low_price == Decimal(98500)
    assert response.payload[0].volume == Decimal(1234567)


def test_kis_forward_valuation_parses_nearest_estimate_period() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(
                200,
                json={"access_token": "token", "expires_in": 3600},
            )
        assert request.url.path.endswith("/quotations/estimate-perform")
        assert request.url.params["SHT_CD"] == "005930"
        return httpx.Response(
            200,
            json={
                "rt_cd": "0",
                "msg_cd": "MCA00000",
                "msg1": "정상처리 되었습니다.",
                "output3": [
                    {
                        "data1": "452335.0",
                        "data2": "753568.0",
                        "data3": "905276.0",
                        "data4": "4306887.0",
                        "data5": "6298333.0",
                    },
                    {
                        "data1": "21310.0",
                        "data2": "49500.0",
                        "data3": "66050.0",
                        "data4": "443617.0",
                        "data5": "642957.0",
                    },
                    {
                        "data1": "-736.0",
                        "data2": "1323.0",
                        "data3": "334.0",
                        "data4": "5716.0",
                        "data5": "449.0",
                    },
                    {
                        "data1": "368.0",
                        "data2": "107.0",
                        "data3": "182.0",
                        "data4": "61.0",
                        "data5": "42.0",
                    },
                ],
                "output4": [
                    {"dt": "2023.12"},
                    {"dt": "2024.12"},
                    {"dt": "2025.12"},
                    {"dt": "2026.12E"},
                    {"dt": "2027.12E"},
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = KisReferenceProvider(
        make_settings(kis_app_key="key", kis_app_secret="secret"),
        client,
    )
    try:
        response = asyncio.run(
            provider.fetch_forward_valuation(
                symbol="005930",
                as_of_date=date(2026, 7, 31),
            )
        )
    finally:
        asyncio.run(client.aclose())

    assert response.state == DataState.AVAILABLE
    assert response.payload is not None
    assert response.payload.fiscal_period == "2026.12E"
    assert response.payload.forward_eps == Decimal("44361.7")
    assert response.payload.forward_per == Decimal("6.1")


def test_kis_current_price_refreshes_an_expired_cached_token() -> None:
    token_calls = 0
    quote_tokens: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.path == "/oauth2/tokenP":
            token_calls += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"token-{token_calls}",
                    "expires_in": 3600,
                },
            )
        authorization = request.headers["authorization"]
        quote_tokens.append(authorization)
        if authorization == "Bearer token-1":
            return httpx.Response(
                500,
                json={
                    "rt_cd": "1",
                    "msg_cd": "EGW00123",
                    "msg1": "기간이 만료된 token 입니다.",
                },
            )
        assert authorization == "Bearer token-2"
        return httpx.Response(
            200,
            json={
                "rt_cd": "0",
                "msg_cd": "MCA00000",
                "msg1": "정상처리 되었습니다.",
                "output": {"stck_prpr": "4190"},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = KisReferenceProvider(
        make_settings(kis_app_key="key", kis_app_secret="secret"),
        client,
    )
    try:
        response = asyncio.run(provider.fetch_current_valuation(symbol="095570"))
    finally:
        asyncio.run(client.aclose())

    assert response.state == DataState.AVAILABLE
    assert response.payload is not None
    assert response.payload[0].current_price == Decimal(4190)
    assert token_calls == 2
    assert quote_tokens[-1] == "Bearer token-2"


def test_phase2_uses_stored_current_metrics_and_dart_industry_peers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "valuation.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    as_of_at = datetime(2026, 7, 30, 20, 0, tzinfo=SEOUL)
    valuation_repository = ValuationRepository()
    with sessions.begin() as session:
        stocks = []
        for index, symbol in enumerate(("005930", "000660")):
            stock = Stock(
                symbol=symbol,
                name_ko=f"검증종목{index}",
                is_active=True,
                is_kospi=True,
                share_class="COMMON",
                source_provider="KRX",
                source_function="test",
                data_state="AVAILABLE",
                as_of_at=as_of_at,
                collected_at=as_of_at,
                data_timing="NOT_APPLICABLE",
            )
            session.add(stock)
            session.flush()
            stocks.append(stock)
            session.add_all(
                [
                    StockClassification(
                        stock_id=stock.id,
                        classification_system="DART_INDUSTRY",
                        classification_code="261",
                        valid_from=as_of_at.date(),
                        source_provider="OpenDART",
                        source_function="기업개황",
                        data_state="AVAILABLE",
                        as_of_at=as_of_at,
                        collected_at=as_of_at,
                        data_timing="NOT_APPLICABLE",
                    ),
                    StockClassification(
                        stock_id=stock.id,
                        classification_system="DART_PARENT_INDUSTRY",
                        classification_code="26",
                        valid_from=as_of_at.date(),
                        source_provider="OpenDART",
                        source_function="기업개황",
                        data_state="AVAILABLE",
                        as_of_at=as_of_at,
                        collected_at=as_of_at,
                        data_timing="NOT_APPLICABLE",
                    ),
                ]
            )
            valuation_repository.upsert_metric(
                session,
                stock_id=stock.id,
                metric_code="CURRENT_PER",
                value=Decimal(10 + index),
                period_end=as_of_at.date(),
                rule_version="official-valuation-v1",
                source_provider="한국투자증권",
                source_function="주식현재가 시세(PER·PBR)",
                collected_at=as_of_at,
                as_of_at=as_of_at,
            )
            valuation_repository.upsert_metric(
                session,
                stock_id=stock.id,
                metric_code="CURRENT_PBR",
                value=Decimal(1 + index),
                period_end=as_of_at.date(),
                rule_version="official-valuation-v1",
                source_provider="한국투자증권",
                source_function="주식현재가 시세(PER·PBR)",
                collected_at=as_of_at,
                as_of_at=as_of_at,
            )

    repository = Phase2InputRepository()
    with sessions() as session:
        current = repository.valuation_for_stock(
            session,
            stocks[0].id,
            as_of_at,
        )
        peers = repository.industry_peers(
            session,
            as_of_at=as_of_at,
            detailed_industry="261",
            parent_industry="26",
        )

    assert current == (Decimal(10), Decimal(1))
    assert {peer.symbol for peer in peers} == {"005930", "000660"}
    assert all(peer.parent_industry == "26" for peer in peers)
    engine.dispose()


def test_stock_detail_reference_uses_verified_peers_across_krx_markets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "detail-reference.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    as_of_at = datetime(2026, 7, 31, 17, 0, tzinfo=SEOUL)
    valuation_repository = ValuationRepository()
    with sessions.begin() as session:
        stocks = []
        for symbol, name, is_kospi in (
            ("067990", "도이치모터스", False),
            ("381970", "케이카", True),
            ("900140", "엘브이엠씨홀딩스", True),
        ):
            stock = Stock(
                symbol=symbol,
                name_ko=name,
                is_active=True,
                is_kospi=is_kospi,
                share_class="COMMON",
                source_provider="KRX",
                source_function="test",
                data_state="AVAILABLE",
                as_of_at=as_of_at,
                collected_at=as_of_at,
                data_timing="NOT_APPLICABLE",
            )
            session.add(stock)
            session.flush()
            stocks.append(stock)
            session.add(
                StockClassification(
                    stock_id=stock.id,
                    classification_system="DART_INDUSTRY",
                    classification_code="451",
                    valid_from=as_of_at.date(),
                    source_provider="OpenDART",
                    source_function="기업개황",
                    data_state="AVAILABLE",
                    as_of_at=as_of_at,
                    collected_at=as_of_at,
                    data_timing="NOT_APPLICABLE",
                )
            )
        for stock, per, pbr in (
            (stocks[0], Decimal("32.69"), Decimal("0.29")),
            (stocks[1], Decimal(8), Decimal("1.2")),
            (stocks[2], Decimal(12), Decimal("0.8")),
        ):
            for metric_code, value in (
                ("CURRENT_PER", per),
                ("CURRENT_PBR", pbr),
            ):
                valuation_repository.upsert_metric(
                    session,
                    stock_id=stock.id,
                    metric_code=metric_code,
                    value=value,
                    period_end=as_of_at.date(),
                    rule_version="official-valuation-v1",
                    source_provider="한국투자증권",
                    source_function="주식현재가 시세(PER·PBR)",
                    collected_at=as_of_at,
                    as_of_at=as_of_at,
                )

    service = ValuationDataService(settings)
    try:
        reference = service.reference_for_symbol(
            "067990",
            as_of_date=as_of_at.date(),
        )
    finally:
        service.close()

    assert reference is not None
    assert reference.comparison_label == "세부 동종업종"
    assert reference.per_median == Decimal(10)
    assert reference.pbr_median == Decimal("1.0")
    assert reference.per_sample_count == 2
    assert reference.pbr_sample_count == 2
    engine.dispose()
