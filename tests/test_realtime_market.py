from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.db.models.market import PriceDaily, Stock
from app.db.session import create_db_engine, create_session_factory
from app.models.market_analysis import MarketRegime, ShockClassification
from app.models.realtime_market import RealtimeIndexTick, RealtimeStockTick
from app.providers.kis_realtime import (
    KIS_INDEX_TR_ID,
    KIS_STOCK_TR_ID,
    KisRealtimeProvider,
)
from app.services.realtime_market_service import (
    RealtimeMarketAnalyzer,
    RealtimeMarketStore,
    realtime_market_constituents,
)
from app.ui import market_dashboard as market_dashboard_ui
from app.utils.dates import SEOUL
from tests.helpers import make_settings, migrate_database


def test_kis_realtime_parser_reads_official_index_breadth_fields() -> None:
    fields = ["0"] * 30
    fields[0] = "0001"
    fields[1] = "101503"
    fields[2] = "2812.34"
    fields[9] = "-1.75"
    fields[23] = "210"
    fields[24] = "50"
    fields[25] = "640"

    tick = KisRealtimeProvider.parse_message(
        f"0|{KIS_INDEX_TR_ID}|1|{'^'.join(fields)}"
    )

    assert isinstance(tick, RealtimeIndexTick)
    assert tick.level == Decimal("2812.34")
    assert tick.change_rate == Decimal("-1.75")
    assert tick.advancing_count == 210
    assert tick.declining_count == 640


def test_kis_realtime_parser_reads_stock_change_rate() -> None:
    fields = ["0"] * 46
    fields[0] = "005930"
    fields[1] = "101504"
    fields[2] = "70100"
    fields[5] = "-2.10"
    fields[33] = "20260731"

    tick = KisRealtimeProvider.parse_message(
        f"0|{KIS_STOCK_TR_ID}|1|{'^'.join(fields)}"
    )

    assert isinstance(tick, RealtimeStockTick)
    assert tick.symbol == "005930"
    assert tick.price == Decimal(70100)
    assert tick.change_rate == Decimal("-2.10")
    assert tick.as_of_at.date().isoformat() == "2026-07-31"


def test_five_minute_provisional_regime_uses_breadth_and_semis() -> None:
    as_of_at = datetime(2026, 7, 31, 10, 17, 42, tzinfo=SEOUL)
    index = RealtimeIndexTick(
        as_of_at=as_of_at,
        level=Decimal("2812.34"),
        change_rate=Decimal("-1.75"),
        advancing_count=210,
        unchanged_count=50,
        declining_count=640,
    )
    stocks = {
        "005930": RealtimeStockTick(
            symbol="005930",
            as_of_at=as_of_at,
            price=Decimal(70100),
            change_rate=Decimal("-3.0"),
        ),
        "000660": RealtimeStockTick(
            symbol="000660",
            as_of_at=as_of_at,
            price=Decimal(181000),
            change_rate=Decimal("-3.5"),
        ),
    }

    snapshot = RealtimeMarketAnalyzer(
        interval_seconds=300,
        rule_version="test-v1",
    ).analyze(index, stocks)

    assert snapshot.market_regime == MarketRegime.ORANGE
    assert snapshot.shock_classification == ShockClassification.SEMICONDUCTOR_LED
    assert snapshot.confidence == Decimal(100)
    assert snapshot.stock_change_rates == {
        "005930": Decimal("-3.0"),
        "000660": Decimal("-3.5"),
    }
    assert snapshot.bucket_started_at.minute == 15
    assert snapshot.bucket_started_at.second == 0


def test_realtime_snapshot_store_round_trips_atomically(tmp_path: Path) -> None:
    as_of_at = datetime(2026, 7, 31, 10, 15, tzinfo=SEOUL)
    snapshot = RealtimeMarketAnalyzer(
        interval_seconds=300,
        rule_version="test-v1",
    ).analyze(
        RealtimeIndexTick(
            as_of_at=as_of_at,
            level=Decimal(2800),
            change_rate=Decimal("0.80"),
            advancing_count=600,
            unchanged_count=100,
            declining_count=300,
        ),
        {},
    )
    store = RealtimeMarketStore(tmp_path / "snapshot.json")

    store.save_snapshot(snapshot)

    assert store.load_snapshot() == snapshot
    assert not (tmp_path / "snapshot.json.tmp").exists()


def test_market_view_uses_last_trading_day_on_weekend_or_holiday() -> None:
    as_of_at = datetime(2026, 7, 31, 15, 30, tzinfo=SEOUL)
    snapshot = RealtimeMarketAnalyzer(
        interval_seconds=300,
        rule_version="test-v1",
    ).analyze(
        RealtimeIndexTick(
            as_of_at=as_of_at,
            level=Decimal(2800),
            change_rate=Decimal("0.5"),
            advancing_count=500,
            unchanged_count=50,
            declining_count=350,
        ),
        {},
    )

    live_label, is_live = market_dashboard_ui._market_view_basis(
        snapshot,
        current=datetime(2026, 7, 31, 15, 30, tzinfo=SEOUL),
    )
    weekend_label, is_weekend_live = market_dashboard_ui._market_view_basis(
        snapshot,
        current=datetime(2026, 8, 1, 10, 0, tzinfo=SEOUL),
    )
    holiday_label, is_holiday_live = market_dashboard_ui._market_view_basis(
        snapshot,
        current=datetime(2026, 8, 3, 10, 0, tzinfo=SEOUL),
    )

    assert (live_label, is_live) == ("실시간", True)
    assert (weekend_label, is_weekend_live) == ("마지막 거래일", False)
    assert (holiday_label, is_holiday_live) == ("마지막 거래일", False)
    assert market_dashboard_ui._realtime_is_newer(date(2026, 7, 30), snapshot)


def test_realtime_constituents_use_latest_kospi_market_cap_weights(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "realtime-caps.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    as_of_at = datetime(2026, 7, 31, 16, 0, tzinfo=SEOUL)
    with sessions.begin() as session:
        for symbol, name, market_cap in (
            ("005930", "삼성전자", Decimal(600)),
            ("000660", "SK하이닉스", Decimal(300)),
            ("035420", "NAVER", Decimal(100)),
        ):
            stock = Stock(
                symbol=symbol,
                name_ko=name,
                is_active=True,
                is_kospi=True,
                share_class="COMMON",
                source_provider="KRX",
                source_function="test",
                data_state="AVAILABLE",
                as_of_at=as_of_at,
                collected_at=as_of_at,
                data_timing="PREVIOUS_CLOSE",
            )
            session.add(stock)
            session.flush()
            session.add(
                PriceDaily(
                    stock_id=stock.id,
                    trade_date=date(2026, 7, 31),
                    currency="KRW",
                    close_price=Decimal(100),
                    market_cap=market_cap,
                    source_provider="KRX",
                    source_function="test",
                    data_state="AVAILABLE",
                    as_of_at=as_of_at,
                    collected_at=as_of_at,
                    data_timing="PREVIOUS_CLOSE",
                )
            )

    constituents = realtime_market_constituents(settings, limit=2)

    assert [item.symbol for item in constituents] == ["005930", "000660"]
    assert constituents[0].market_weight == Decimal("0.6")
    assert constituents[1].market_weight == Decimal("0.3")
    engine.dispose()
