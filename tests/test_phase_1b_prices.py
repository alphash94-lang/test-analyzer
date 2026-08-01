from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from app.config import get_settings
from app.db.models.market import PriceDaily
from app.db.models.quality import ApiRawResponse
from app.db.session import create_db_engine, create_session_factory
from app.models.metadata import DataState
from app.models.price import KrxDailyPriceItem
from app.providers.krx_price import KrxDailyPriceProvider
from app.repositories.price_repository import PriceRepository
from app.repositories.stock_repository import StockRepository
from app.services.price_service import PriceService
from app.services.stock_classification import classify_krx_stock
from app.utils.dates import now_kst
from tests.helpers import make_settings, migrate_database
from tests.test_stock_classification import minimum_item


def daily_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "BAS_DD": "20260729",
        "ISU_CD": "000001",
        "ISU_NM": "가격검증",
        "MKT_NM": "KOSPI",
        "SECT_TP_NM": "",
        "TDD_CLSPRC": "10,000",
        "CMPPREVDD_PRC": "100",
        "FLUC_RT": "1.01",
        "TDD_OPNPRC": "9,900",
        "TDD_HGPRC": "10,100",
        "TDD_LWPRC": "9,800",
        "ACC_TRDVOL": "1,234",
        "ACC_TRDVAL": "12,340,000",
        "MKTCAP": "100,000,000",
        "LIST_SHRS": "10,000",
    }
    row.update(overrides)
    return row


def test_daily_price_contract_parses_official_numbers() -> None:
    item = KrxDailyPriceItem.model_validate(daily_row())

    assert item.trade_date == date(2026, 7, 29)
    assert item.close_price == Decimal(10000)
    assert item.volume == Decimal(1234)


def test_daily_price_contract_rejects_inconsistent_ohlc() -> None:
    with pytest.raises(ValueError, match="high price"):
        KrxDailyPriceItem.model_validate(daily_row(TDD_HGPRC="9,950"))


def test_daily_price_contract_distinguishes_zero_from_missing() -> None:
    zero = KrxDailyPriceItem.model_validate(
        daily_row(
            TDD_CLSPRC="0",
            TDD_OPNPRC="0",
            TDD_HGPRC="0",
            TDD_LWPRC="0",
            ACC_TRDVOL="0",
            ACC_TRDVAL="0",
            MKTCAP="0",
            LIST_SHRS="0",
        )
    )

    assert zero.close_price == Decimal(0)
    with pytest.raises(ValueError, match="must not be null"):
        KrxDailyPriceItem.model_validate(daily_row(TDD_CLSPRC=None))


def test_daily_price_contract_accepts_official_no_trade_ohl_pattern() -> None:
    item = KrxDailyPriceItem.model_validate(
        daily_row(
            TDD_CLSPRC="10,000",
            TDD_OPNPRC="0",
            TDD_HGPRC="0",
            TDD_LWPRC="0",
            ACC_TRDVOL="0",
            ACC_TRDVAL="0",
        )
    )

    assert item.close_price == Decimal(10000)
    assert item.volume == Decimal(0)


def test_provider_rejects_response_for_different_date() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["AUTH_KEY"] == "test-key"
        return httpx.Response(
            200,
            request=request,
            json={"OutBlock_1": [daily_row(BAS_DD="20260728")]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = make_settings(krx_api_key="test-key")
    provider = KrxDailyPriceProvider(settings, client)
    response = asyncio.run(provider.fetch(as_of_date=date(2026, 7, 29)))
    asyncio.run(client.aclose())

    assert response.state == DataState.FETCH_FAILED
    assert response.error_code == "SCHEMA_VALIDATION_FAILED"
    assert response.payload is None


def test_kosdaq_daily_price_provider_uses_kosdaq_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/sto/ksq_bydd_trd")
        return httpx.Response(
            200,
            request=request,
            json={
                "OutBlock_1": [
                    daily_row(
                        ISU_CD="098120",
                        ISU_NM="마이크로컨텍솔",
                        MKT_NM="KOSDAQ",
                    )
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = KrxDailyPriceProvider(
        make_settings(krx_api_key="test-key"),
        client,
        market="KOSDAQ",
    )
    response = asyncio.run(provider.fetch(as_of_date=date(2026, 7, 29)))
    asyncio.run(client.aclose())

    assert response.state == DataState.AVAILABLE
    assert response.payload is not None
    assert response.payload[0].market_name == "KOSDAQ"
    assert response.metadata.function_name == "코스닥 일별매매정보"


def test_http_error_is_not_stored_as_available_price(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "price-http-error.db", monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            request=request,
            json={"error": "upstream failure"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = make_settings(
        database_url=database_url,
        krx_api_key="test-key",
        raw_data_dir=tmp_path / "raw",
    )
    provider = KrxDailyPriceProvider(settings, client)
    service = PriceService(settings, provider=provider)
    summary = asyncio.run(service.refresh(date(2026, 7, 29)))
    service.close()
    asyncio.run(client.aclose())

    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions() as session:
        prices = session.query(PriceDaily).count()
        raw = session.query(ApiRawResponse).one()

    assert summary.state == DataState.FETCH_FAILED.value
    assert prices == 0
    assert raw.http_status == 500
    assert raw.normalized_success is False
    assert raw.data_state == DataState.FETCH_FAILED.value
    engine.dispose()


def test_repository_upserts_idempotently_and_reports_unmatched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "prices.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    stock_repository = StockRepository()
    price_repository = PriceRepository()
    collected_at = now_kst()

    master = minimum_item(name="가격검증").model_copy(
        update={"issue_code": "KR7000001001"}
    )
    matched = KrxDailyPriceItem.model_validate(daily_row())
    unmatched = KrxDailyPriceItem.model_validate(
        daily_row(ISU_CD="999999", ISU_NM="미매핑")
    )
    with sessions.begin() as session:
        stock_repository.upsert_krx_records(
            session,
            [classify_krx_stock(master)],
            as_of_at=collected_at,
            collected_at=collected_at,
        )
        first = price_repository.upsert_krx_records(
            session,
            [matched, unmatched],
            as_of_at=collected_at,
            collected_at=collected_at,
        )
        second = price_repository.upsert_krx_records(
            session,
            [matched],
            as_of_at=collected_at,
            collected_at=collected_at,
        )

    with sessions() as session:
        latest = price_repository.latest_for_symbols(session, ["000001"])
        stored_row = session.query(PriceDaily).one()

    assert first == (1, 1)
    assert second == (1, 0)
    assert stored_row.currency is None
    assert latest["000001"].close_price == Decimal(10000)
    assert latest["000001"].is_adjusted is False
    assert stored_row.adjustment_status == "RAW_OFFICIAL"
    assert latest["000001"].collected_at.utcoffset() is not None
    engine.dispose()


def test_stock_search_displays_only_stored_official_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "price-ui.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    collected_at = now_kst()
    with sessions.begin() as session:
        StockRepository().upsert_krx_records(
            session,
            [
                classify_krx_stock(
                    minimum_item(name="가격화면").model_copy(
                        update={"issue_code": "KR7000001001"}
                    )
                )
            ],
            as_of_at=collected_at,
            collected_at=collected_at,
        )
        PriceRepository().upsert_krx_records(
            session,
            [KrxDailyPriceItem.model_validate(daily_row(ISU_NM="가격화면"))],
            as_of_at=collected_at,
            collected_at=collected_at,
        )
    engine.dispose()
    get_settings.cache_clear()

    app = AppTest.from_file("app/main.py", default_timeout=15).run()
    app.radio[0].set_value("개별 종목 검색").run()
    app.text_input[0].set_value("000001").run()

    assert not app.exception
    frame = app.dataframe[0].value
    assert frame.loc[0, "최근 확정종가"] == "10,000 (단위 미검증)"
    assert frame.loc[0, "가격 기준일"] == "2026-07-29"
    assert "KRX 유가증권 일별매매정보" in frame.loc[0, "가격 출처·상태"]


def test_latest_price_preserves_missing_market_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "price-missing.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    collected_at = now_kst()
    repository = PriceRepository()
    with sessions.begin() as session:
        StockRepository().upsert_krx_records(
            session,
            [
                classify_krx_stock(
                    minimum_item(name="결측검증").model_copy(
                        update={"issue_code": "KR7000001001"}
                    )
                )
            ],
            as_of_at=collected_at,
            collected_at=collected_at,
        )
        repository.upsert_krx_records(
            session,
            [KrxDailyPriceItem.model_validate(daily_row(ISU_NM="결측검증"))],
            as_of_at=collected_at,
            collected_at=collected_at,
        )
        row = session.query(PriceDaily).one()
        row.volume = None
        row.trading_value = None
        row.market_cap = None

    with sessions() as session:
        latest = repository.latest_for_symbols(session, ["000001"])["000001"]

    assert latest.volume is None
    assert latest.trading_value is None
    assert latest.market_cap is None
    engine.dispose()


def test_price_mapping_uses_short_symbol_when_master_issue_code_is_duplicated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "price-conflict.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    collected_at = now_kst()
    repository = PriceRepository()
    with sessions.begin() as session:
        first_master = minimum_item(name="중복하나").model_copy(
            update={"issue_code": "KR7000001001"}
        )
        second_master = minimum_item(name="중복둘").model_copy(
            update={
                "symbol": "000002",
                "issue_code": "KR7000001001",
            }
        )
        StockRepository().upsert_krx_records(
            session,
            [
                classify_krx_stock(first_master),
                classify_krx_stock(second_master),
            ],
            as_of_at=collected_at,
            collected_at=collected_at,
        )
        stored, unmatched = repository.upsert_krx_records(
            session,
            [KrxDailyPriceItem.model_validate(daily_row())],
            as_of_at=collected_at,
            collected_at=collected_at,
        )
        price_count = session.query(PriceDaily).count()

    assert (stored, unmatched) == (1, 0)
    assert price_count == 1
    engine.dispose()
