from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.backtest import (
    BacktestDataset,
    BacktestFoldInput,
    BacktestRules,
    DividendPayment,
    IndexObservation,
    PointInTimePosition,
    PriceObservation,
    UniverseMethod,
)
from app.models.metadata import DataState
from app.services.backtest_calculator import calculate_backtest
from app.services.backtest_service import BacktestService
from app.utils.dates import SEOUL
from tests.helpers import make_settings, migrate_database


def _price(
    trade_date: date,
    *,
    open_price: str,
    close_price: str,
) -> PriceObservation:
    return PriceObservation(
        trade_date=trade_date,
        open_price=Decimal(open_price),
        close_price=Decimal(close_price),
        currency="KRW",
        source_provider="KIS",
        source_function="국내주식기간별시세",
        is_adjusted=True,
        adjustment_status="VERIFIED",
        collected_at=datetime.combine(
            trade_date,
            datetime.min.time(),
            tzinfo=SEOUL,
        ),
    )


def _benchmark(
    trade_date: date,
    *,
    open_price: str,
    close_price: str,
) -> IndexObservation:
    return IndexObservation(
        trade_date=trade_date,
        open_price=Decimal(open_price),
        close_price=Decimal(close_price),
        source_provider="KRX",
        source_function="KOSPI 시리즈 일별시세정보",
        collected_at=datetime.combine(
            trade_date,
            datetime.min.time(),
            tzinfo=SEOUL,
        ),
    )


def _position(
    *,
    stock_id: int,
    symbol: str,
    signal_date: date,
    weight: str = "0.5",
    entry_price: str = "100",
    exit_price: str = "110",
    industry: str = "IND-A",
) -> PointInTimePosition:
    return PointInTimePosition(
        stock_id=stock_id,
        symbol=symbol,
        name=f"검증-{symbol}",
        target_weight=Decimal(weight),
        industry_code=industry,
        recommendation_category="READY_FOR_RECOVERY",
        listed_on=date(2010, 1, 1),
        delisted_on=None,
        financial_filing_dates_used=(signal_date.replace(day=1),),
        correction_filing_dates_used=(),
        financial_history_complete=True,
        correction_history_complete=True,
        dividend_history_complete=True,
        prices=(
            _price(
                signal_date.replace(day=2),
                open_price="95",
                close_price="96",
            ),
            _price(
                signal_date.replace(day=6),
                open_price=entry_price,
                close_price=entry_price,
            ),
            _price(
                date(signal_date.year, signal_date.month + 1, 6),
                open_price=exit_price,
                close_price=exit_price,
            ),
            _price(
                date(signal_date.year, signal_date.month + 3, 6),
                open_price=exit_price,
                close_price=exit_price,
            ),
            _price(
                date(signal_date.year, signal_date.month + 6, 6),
                open_price=exit_price,
                close_price=exit_price,
            ),
            _price(
                date(signal_date.year + 1, signal_date.month, 6),
                open_price=exit_price,
                close_price=exit_price,
            ),
        ),
        dividends=(
            DividendPayment(
                business_year=signal_date.year - 1,
                payment_date=date(signal_date.year, signal_date.month + 1, 5),
                dps=Decimal(2),
                currency="KRW",
                filing_date=signal_date.replace(day=2),
                receipt_no=f"{signal_date:%Y%m%d}000001",
                correction_of_receipt_no=None,
                is_confirmed=True,
                is_estimate=False,
                source_provider="OpenDART",
            ),
        ),
    )


def _fold(
    signal_date: date,
    *,
    position: PointInTimePosition,
    includes_delisted: bool = True,
    universe_complete: bool = True,
) -> BacktestFoldInput:
    return BacktestFoldInput(
        signal_at=datetime.combine(
            signal_date,
            datetime.min.time(),
            tzinfo=SEOUL,
        ),
        universe_as_of=signal_date,
        universe_method=UniverseMethod.POINT_IN_TIME_HISTORY,
        universe_snapshot_source="KRX historical membership fixture",
        universe_input_hash=("a" * 63 + str(signal_date.month % 10)),
        universe_complete=universe_complete,
        includes_delisted=includes_delisted,
        universe_symbols=(position.symbol, "999999"),
        score_version="phase4-score-v1",
        recommendation_rule_version="phase4-rule-v2",
        market_rule_version="phase3-rule-v2",
        recommendation_config_hash="b" * 64,
        market_regime="YELLOW",
        positions=(position,),
        benchmarks={
            "코스피": (
                _benchmark(
                    signal_date.replace(day=6),
                    open_price="1000",
                    close_price="1000",
                ),
                _benchmark(
                    date(signal_date.year, signal_date.month + 1, 6),
                    open_price="1050",
                    close_price="1050",
                ),
                _benchmark(
                    date(signal_date.year, signal_date.month + 3, 6),
                    open_price="1070",
                    close_price="1070",
                ),
                _benchmark(
                    date(signal_date.year, signal_date.month + 6, 6),
                    open_price="1090",
                    close_price="1090",
                ),
                _benchmark(
                    date(signal_date.year + 1, signal_date.month, 6),
                    open_price="1100",
                    close_price="1100",
                ),
            )
        },
    )


def _dataset(*folds: BacktestFoldInput) -> BacktestDataset:
    observed_dates = [
        observation.trade_date
        for fold in folds
        for position in fold.positions
        for observation in position.prices
    ] + [
        observation.trade_date
        for fold in folds
        for observations in fold.benchmarks.values()
        for observation in observations
    ]
    return BacktestDataset(
        start_date=min(item.signal_at.date() for item in folds),
        end_date=max(observed_dates),
        folds=folds,
        source_name="verified point-in-time fixture",
        known_survival_bias=(),
    )


def test_backtest_refuses_current_universe_or_missing_delisted_history() -> None:
    signal_date = date(2025, 1, 5)
    position = _position(
        stock_id=1,
        symbol="000001",
        signal_date=signal_date,
    )
    fold = _fold(
        signal_date,
        position=position,
        includes_delisted=False,
    ).model_copy(update={"universe_method": UniverseMethod.CURRENT_MASTER})

    result = calculate_backtest(
        _dataset(fold),
        BacktestRules(minimum_walk_forward_folds=1),
    )

    assert result.state == DataState.MISSING
    assert result.metrics is None
    assert (
        result.universe_construction_method
        == UniverseMethod.CURRENT_MASTER.value
    )
    assert "POINT_IN_TIME_UNIVERSE_REQUIRED" in result.missing_data
    assert "DELISTED_UNIVERSE_NOT_VERIFIED" in result.missing_data


def test_financial_and_correction_data_are_available_next_trading_day_only() -> None:
    signal_date = date(2025, 1, 5)
    position = _position(
        stock_id=1,
        symbol="000001",
        signal_date=signal_date,
    ).model_copy(
        update={
            "financial_filing_dates_used": (signal_date,),
            "correction_filing_dates_used": (signal_date,),
        }
    )

    result = calculate_backtest(
        _dataset(_fold(signal_date, position=position)),
        BacktestRules(minimum_walk_forward_folds=1),
    )

    assert result.state == DataState.MISSING
    assert result.metrics is None
    assert any(
        item.startswith("FINANCIAL_NOT_YET_AVAILABLE:000001")
        for item in result.missing_data
    )
    assert any(
        item.startswith("CORRECTION_NOT_YET_AVAILABLE:000001")
        for item in result.missing_data
    )


def test_next_trading_open_adjusted_price_dividend_and_cost_are_used() -> None:
    signal_date = date(2025, 1, 5)
    position = _position(
        stock_id=1,
        symbol="000001",
        signal_date=signal_date,
        entry_price="100",
        exit_price="110",
    )
    rules = BacktestRules(
        transaction_cost_bps=Decimal(10),
        minimum_walk_forward_folds=1,
    )

    result = calculate_backtest(
        _dataset(_fold(signal_date, position=position)),
        rules,
    )

    assert result.state == DataState.AVAILABLE
    assert result.metrics is not None
    horizon = result.folds[0].positions[0].horizons[0]
    assert result.folds[0].execution_date == date(2025, 1, 6)
    assert horizon.exit_date == date(2025, 2, 6)
    assert horizon.dividend_per_share == Decimal(2)
    assert horizon.gross_return == Decimal("0.12")
    assert horizon.transaction_cost_return == Decimal("0.0021")
    assert horizon.net_return == Decimal("0.1179")


def test_unverified_adjusted_price_is_never_used() -> None:
    signal_date = date(2025, 1, 5)
    position = _position(
        stock_id=1,
        symbol="000001",
        signal_date=signal_date,
    )
    bad_prices = tuple(
        item.model_copy(update={"adjustment_status": "NOT_VERIFIED"})
        for item in position.prices
    )
    position = position.model_copy(update={"prices": bad_prices})

    result = calculate_backtest(
        _dataset(_fold(signal_date, position=position)),
        BacktestRules(minimum_walk_forward_folds=1),
    )

    assert result.state == DataState.MISSING
    assert result.metrics is None
    assert "VERIFIED_ADJUSTED_ENTRY_PRICE_MISSING:000001" in result.missing_data


def test_delisted_position_requires_official_settlement_instead_of_disappearing() -> None:
    signal_date = date(2025, 1, 5)
    position = _position(
        stock_id=1,
        symbol="000001",
        signal_date=signal_date,
    ).model_copy(update={"delisted_on": date(2025, 1, 31)})

    missing = calculate_backtest(
        _dataset(_fold(signal_date, position=position)),
        BacktestRules(minimum_walk_forward_folds=1),
    )
    assert missing.state == DataState.MISSING
    assert "DELISTING_SETTLEMENT_MISSING:000001:1M" in missing.missing_data

    settled_position = position.model_copy(
        update={
            "delisting_cash_per_share": Decimal(40),
            "delisting_cash_currency": "KRW",
            "delisting_cash_source": "KRX official delisting settlement",
        }
    )
    available = calculate_backtest(
        _dataset(_fold(signal_date, position=settled_position)),
        BacktestRules(minimum_walk_forward_folds=1),
    )
    horizon = available.folds[0].positions[0].horizons[0]
    assert horizon.exit_reason == "DELISTING_SETTLEMENT"
    assert horizon.exit_date == date(2025, 1, 31)
    assert horizon.gross_return == Decimal("-0.6")


def test_walk_forward_metrics_are_reproducible_and_segmented() -> None:
    first_date = date(2025, 1, 5)
    second_date = date(2025, 3, 5)
    first = _fold(
        first_date,
        position=_position(
            stock_id=1,
            symbol="000001",
            signal_date=first_date,
            industry="IND-A",
        ),
    )
    second = _fold(
        second_date,
        position=_position(
            stock_id=2,
            symbol="000002",
            signal_date=second_date,
            entry_price="100",
            exit_price="90",
            industry="IND-B",
        ),
    ).model_copy(update={"market_regime": "RED"})
    dataset = _dataset(first, second)
    rules = BacktestRules(transaction_cost_bps=Decimal(10))

    first_result = calculate_backtest(dataset, rules)
    second_result = calculate_backtest(dataset, rules)

    assert first_result.state == DataState.AVAILABLE
    assert first_result.input_data_hash == second_result.input_data_hash
    assert first_result.metrics == second_result.metrics
    assert first_result.metrics is not None
    assert set(first_result.metrics.market_regime_performance) == {
        "YELLOW",
        "RED",
    }
    assert set(first_result.metrics.industry_performance) == {
        "IND-A",
        "IND-B",
    }
    assert first_result.metrics.average_turnover > 0
    assert first_result.metrics.total_transaction_cost_return > 0


def test_backtest_result_is_reused_for_identical_config_and_input(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "phase6.db"
    database_url = migrate_database(database_path, monkeypatch)
    settings = make_settings(
        database_url=database_url,
        phase6_minimum_walk_forward_folds=1,
    )
    service = BacktestService(settings)
    dataset = _dataset(
        _fold(
            date(2025, 1, 5),
            position=_position(
                stock_id=1,
                symbol="000001",
                signal_date=date(2025, 1, 5),
            ),
        )
    )
    try:
        first = service.run(dataset)
        second = service.run(dataset)
    finally:
        service.close()

    assert first.run_id is not None
    assert second.run_id == first.run_id
    assert second.input_data_hash == first.input_data_hash


def test_empty_dataset_saves_missing_without_fake_metrics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "phase6-empty.db"
    database_url = migrate_database(database_path, monkeypatch)
    settings = make_settings(database_url=database_url)
    service = BacktestService(settings)
    try:
        result = service.run(
            BacktestDataset(
                start_date=date(2025, 1, 1),
                end_date=date(2025, 12, 31),
                folds=(),
                source_name="empty operational database",
                known_survival_bias=(
                    "시점별 유니버스와 상장폐지 이력이 없습니다.",
                ),
            )
        )
    finally:
        service.close()

    assert result.state == DataState.MISSING
    assert result.metrics is None
    assert result.run_id is not None
    assert "POINT_IN_TIME_DATASET_MISSING" in result.missing_data
    assert "WALK_FORWARD_FOLDS_INSUFFICIENT" in result.missing_data


def test_latest_dividend_correction_is_used_once_without_double_counting() -> None:
    signal_date = date(2025, 1, 5)
    position = _position(
        stock_id=1,
        symbol="000001",
        signal_date=signal_date,
    )
    original = position.dividends[0]
    correction = original.model_copy(
        update={
            "dps": Decimal(1),
            "filing_date": date(2025, 1, 20),
            "receipt_no": "20250120000002",
            "correction_of_receipt_no": original.receipt_no,
        }
    )
    position = position.model_copy(
        update={"dividends": (original, correction)}
    )

    result = calculate_backtest(
        _dataset(_fold(signal_date, position=position)),
        BacktestRules(minimum_walk_forward_folds=1),
    )

    assert result.state == DataState.AVAILABLE
    horizon = result.folds[0].positions[0].horizons[0]
    assert horizon.dividend_per_share == Decimal(1)
    assert horizon.gross_return == Decimal("0.11")


def test_future_dividend_correction_is_not_applied_retroactively() -> None:
    signal_date = date(2025, 1, 5)
    position = _position(
        stock_id=1,
        symbol="000001",
        signal_date=signal_date,
    )
    original = position.dividends[0]
    future_correction = original.model_copy(
        update={
            "dps": Decimal(9),
            "filing_date": date(2025, 3, 1),
            "receipt_no": "20250301000002",
            "correction_of_receipt_no": original.receipt_no,
        }
    )
    position = position.model_copy(
        update={"dividends": (original, future_correction)}
    )

    result = calculate_backtest(
        _dataset(_fold(signal_date, position=position)),
        BacktestRules(minimum_walk_forward_folds=1),
    )

    assert result.state == DataState.AVAILABLE
    one_month = result.folds[0].positions[0].horizons[0]
    three_months = result.folds[0].positions[0].horizons[1]
    assert one_month.dividend_per_share == Decimal(2)
    assert three_months.dividend_per_share == Decimal(9)


def test_result_cannot_use_observations_after_declared_data_period() -> None:
    signal_date = date(2025, 1, 5)
    fold = _fold(
        signal_date,
        position=_position(
            stock_id=1,
            symbol="000001",
            signal_date=signal_date,
        ),
    )
    dataset = _dataset(fold).model_copy(update={"end_date": date(2026, 1, 5)})

    result = calculate_backtest(
        dataset,
        BacktestRules(minimum_walk_forward_folds=1),
    )

    assert result.state == DataState.MISSING
    assert result.metrics is None
    assert "RESULT_OUTSIDE_DECLARED_DATA_PERIOD:000001:12M" in (
        result.missing_data
    )


def test_configured_high_dividend_benchmark_is_reported() -> None:
    signal_date = date(2025, 1, 5)
    fold = _fold(
        signal_date,
        position=_position(
            stock_id=1,
            symbol="000001",
            signal_date=signal_date,
        ),
    )
    high_dividend_points = tuple(
        item.model_copy(
            update={
                "open_price": Decimal(1000),
                "close_price": (
                    Decimal(1000)
                    if index == 0
                    else Decimal(1000 + index * 10)
                ),
                "source_function": "KRX 고배당 지수 일별시세",
            }
        )
        for index, item in enumerate(fold.benchmarks["코스피"])
    )
    fold = fold.model_copy(
        update={
            "benchmarks": {
                **fold.benchmarks,
                "코스피 고배당": high_dividend_points,
            }
        }
    )

    result = calculate_backtest(
        _dataset(fold),
        BacktestRules(
            minimum_walk_forward_folds=1,
            high_dividend_benchmark="코스피 고배당",
        ),
    )

    assert result.state == DataState.AVAILABLE
    assert result.metrics is not None
    assert result.metrics.high_dividend_benchmark_cumulative_return == Decimal(
        "0.01"
    )
    assert result.metrics.high_dividend_benchmark_excess_return is not None
    assert result.folds[0].high_dividend_benchmark_returns["1M"] == Decimal(
        "0.01"
    )


def test_phase6_source_and_version_lineage_rejects_blank_or_non_hash_values() -> None:
    with pytest.raises(ValidationError):
        IndexObservation(
            trade_date=date(2025, 1, 6),
            open_price=Decimal(100),
            close_price=Decimal(101),
            source_provider=" ",
            source_function="KOSPI 시리즈 일별시세정보",
            collected_at=datetime(2025, 1, 6, tzinfo=SEOUL),
        )

    with pytest.raises(ValidationError):
        _price(
            date(2025, 1, 6),
            open_price="100",
            close_price="101",
        ).__class__.model_validate(
            {
                **_price(
                    date(2025, 1, 6),
                    open_price="100",
                    close_price="101",
                ).model_dump(),
                "currency": " ",
            }
        )

    with pytest.raises(ValidationError):
        DividendPayment(
            business_year=2024,
            payment_date=date(2025, 2, 5),
            dps=Decimal(1),
            currency=" ",
            filing_date=date(2025, 1, 20),
            receipt_no=" ",
            correction_of_receipt_no=None,
            is_confirmed=True,
            is_estimate=False,
            source_provider=" ",
        )

    with pytest.raises(ValidationError):
        BacktestRules(high_dividend_benchmark=" ")

    signal_date = date(2025, 1, 5)
    fold = _fold(
        signal_date,
        position=_position(
            stock_id=1,
            symbol="000001",
            signal_date=signal_date,
        ),
    )
    with pytest.raises(ValidationError):
        fold.model_copy(
            update={
                "score_version": " ",
                "universe_input_hash": "z" * 64,
            }
        ).__class__.model_validate(
            {
                **fold.model_dump(),
                "score_version": " ",
                "universe_input_hash": "z" * 64,
            }
        )


def test_delisting_flag_only_marks_horizons_that_reach_delisting() -> None:
    signal_date = date(2025, 1, 5)
    position = _position(
        stock_id=1,
        symbol="000001",
        signal_date=signal_date,
    ).model_copy(update={"delisted_on": date(2027, 1, 31)})

    result = calculate_backtest(
        _dataset(_fold(signal_date, position=position)),
        BacktestRules(minimum_walk_forward_folds=1),
    )

    assert result.state == DataState.AVAILABLE
    assert result.folds[0].positions[0].was_delisted is False


def test_distinct_dividends_paid_same_day_are_both_included() -> None:
    signal_date = date(2025, 1, 5)
    position = _position(
        stock_id=1,
        symbol="000001",
        signal_date=signal_date,
    )
    regular = position.dividends[0]
    special = regular.model_copy(
        update={
            "dps": Decimal(3),
            "receipt_no": "20250102000099",
            "correction_of_receipt_no": None,
        }
    )
    position = position.model_copy(
        update={"dividends": (regular, special)}
    )

    result = calculate_backtest(
        _dataset(_fold(signal_date, position=position)),
        BacktestRules(minimum_walk_forward_folds=1),
    )

    assert result.state == DataState.AVAILABLE
    one_month = result.folds[0].positions[0].horizons[0]
    assert one_month.dividend_per_share == Decimal(5)


def test_result_exposes_input_source_collection_time_and_drawdown_method() -> None:
    signal_date = date(2025, 1, 5)
    result = calculate_backtest(
        _dataset(
            _fold(
                signal_date,
                position=_position(
                    stock_id=1,
                    symbol="000001",
                    signal_date=signal_date,
                ),
            )
        ),
        BacktestRules(minimum_walk_forward_folds=1),
    )

    assert result.input_source_name == "verified point-in-time fixture"
    assert result.latest_input_collected_at is not None
    assert result.latest_input_collected_at.tzinfo is not None
    assert result.drawdown_method == (
        "WALK_FORWARD_PRIMARY_HORIZON_FOLD_ENDPOINTS"
    )
