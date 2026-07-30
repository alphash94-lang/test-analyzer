from __future__ import annotations

import calendar
import json
from datetime import date
from decimal import Decimal
from hashlib import sha256

from app.models.backtest import (
    BacktestFoldInput,
    BacktestFoldResult,
    BacktestHorizonResult,
    BacktestPositionResult,
    BacktestRules,
    DividendPayment,
    PointInTimePosition,
    PriceObservation,
    UniverseMethod,
)


def canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def horizon_label(months: int) -> str:
    return f"{months}M"


def add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _valid_prices(
    position: PointInTimePosition,
    rules: BacktestRules,
) -> list[PriceObservation]:
    return sorted(
        (
            item
            for item in position.prices
            if item.source_provider == rules.adjusted_price_provider
            and item.is_adjusted is True
            and item.adjustment_status == "VERIFIED"
            and item.currency
            and item.open_price is not None
            and item.close_price is not None
        ),
        key=lambda item: item.trade_date,
    )


def _next_price(
    prices: list[PriceObservation],
    after_date: date,
) -> PriceObservation | None:
    return next(
        (item for item in prices if item.trade_date > after_date),
        None,
    )


def _exit_price(
    prices: list[PriceObservation],
    target_date: date,
    *,
    currency: str,
) -> PriceObservation | None:
    return next(
        (
            item
            for item in prices
            if item.trade_date >= target_date
            and item.currency == currency
            and item.close_price is not None
        ),
        None,
    )


def _benchmark_horizons(
    fold: BacktestFoldInput,
    rules: BacktestRules,
    *,
    data_end: date,
) -> tuple[dict[int, Decimal], dict[int, Decimal], list[str]]:
    required = [rules.primary_benchmark]
    if rules.high_dividend_benchmark is not None:
        required.append(rules.high_dividend_benchmark)
    issues: list[str] = []
    returns_by_name: dict[str, dict[int, Decimal]] = {}
    for benchmark_name in required:
        points = sorted(
            fold.benchmarks.get(benchmark_name, ()),
            key=lambda item: item.trade_date,
        )
        entry = next(
            (
                item
                for item in points
                if item.trade_date > fold.signal_at.date()
            ),
            None,
        )
        if entry is None:
            issues.append(f"BENCHMARK_ENTRY_MISSING:{benchmark_name}")
            continue
        benchmark_returns: dict[int, Decimal] = {}
        for months in rules.horizon_months:
            target = add_months(fold.signal_at.date(), months)
            exit_point = next(
                (item for item in points if item.trade_date >= target),
                None,
            )
            if exit_point is None:
                issues.append(
                    f"BENCHMARK_EXIT_MISSING:{benchmark_name}:{months}M"
                )
                continue
            if exit_point.trade_date > data_end:
                issues.append(
                    f"RESULT_OUTSIDE_DECLARED_DATA_PERIOD:"
                    f"{benchmark_name}:{months}M"
                )
            benchmark_returns[months] = (
                exit_point.close_price - entry.open_price
            ) / entry.open_price
        returns_by_name[benchmark_name] = benchmark_returns
    return (
        returns_by_name.get(rules.primary_benchmark, {}),
        (
            {}
            if rules.high_dividend_benchmark is None
            else returns_by_name.get(rules.high_dividend_benchmark, {})
        ),
        issues,
    )


def _evidence_issues(
    position: PointInTimePosition,
    fold: BacktestFoldInput,
    prices: list[PriceObservation],
) -> list[str]:
    issues: list[str] = []
    signal_date = fold.signal_at.date()
    if position.listed_on > signal_date or (
        position.delisted_on is not None
        and position.delisted_on < signal_date
    ):
        issues.append(f"UNIVERSE_MEMBERSHIP_INVALID:{position.symbol}")
    if not position.financial_history_complete:
        issues.append(f"FINANCIAL_HISTORY_INCOMPLETE:{position.symbol}")
    if not position.correction_history_complete:
        issues.append(f"CORRECTION_HISTORY_INCOMPLETE:{position.symbol}")
    if not position.dividend_history_complete:
        issues.append(f"DIVIDEND_HISTORY_INCOMPLETE:{position.symbol}")
    if not position.financial_filing_dates_used:
        issues.append(f"FINANCIAL_LINEAGE_MISSING:{position.symbol}")

    for filing_date in position.financial_filing_dates_used:
        first_tradable = _next_price(prices, filing_date)
        if first_tradable is None or signal_date < first_tradable.trade_date:
            issues.append(
                f"FINANCIAL_NOT_YET_AVAILABLE:{position.symbol}:{filing_date}"
            )
    for filing_date in position.correction_filing_dates_used:
        first_tradable = _next_price(prices, filing_date)
        if first_tradable is None or signal_date < first_tradable.trade_date:
            issues.append(
                f"CORRECTION_NOT_YET_AVAILABLE:{position.symbol}:{filing_date}"
            )
    return issues


def _latest_dividends_available_by(
    position: PointInTimePosition,
    *,
    entry_date: date,
    exit_date: date,
    currency: str,
) -> tuple[DividendPayment, ...]:
    latest: dict[tuple[date, str, str], DividendPayment] = {}
    for item in position.dividends:
        if not (
            entry_date < item.payment_date <= exit_date
            and item.currency == currency
            and item.is_confirmed
            and not item.is_estimate
            and item.filing_date <= exit_date
        ):
            continue
        event_receipt = item.correction_of_receipt_no or item.receipt_no
        key = (item.payment_date, item.currency, event_receipt)
        previous = latest.get(key)
        if previous is None or (
            item.filing_date,
            item.receipt_no,
        ) > (
            previous.filing_date,
            previous.receipt_no,
        ):
            latest[key] = item
    return tuple(latest.values())


def _position_result(
    position: PointInTimePosition,
    fold: BacktestFoldInput,
    rules: BacktestRules,
    benchmark_returns: dict[int, Decimal],
    *,
    data_end: date,
) -> tuple[BacktestPositionResult | None, list[str]]:
    prices = _valid_prices(position, rules)
    issues = _evidence_issues(position, fold, prices)
    entry = _next_price(prices, fold.signal_at.date())
    if entry is None or entry.open_price is None or entry.currency is None:
        issues.append(
            f"VERIFIED_ADJUSTED_ENTRY_PRICE_MISSING:{position.symbol}"
        )
        return None, issues
    if entry.trade_date > fold.signal_at.date() and (
        position.delisted_on is not None
        and entry.trade_date > position.delisted_on
    ):
        issues.append(f"NEXT_TRADABLE_PRICE_AFTER_DELISTING:{position.symbol}")
        return None, issues

    cost_rate = rules.transaction_cost_bps / Decimal(10_000)
    horizons: list[BacktestHorizonResult] = []
    for months in rules.horizon_months:
        target_date = add_months(fold.signal_at.date(), months)
        exit_reason = "ADJUSTED_CLOSE_ON_OR_AFTER_HORIZON"
        if (
            position.delisted_on is not None
            and position.delisted_on <= target_date
        ):
            if (
                position.delisting_cash_per_share is None
                or position.delisting_cash_currency != entry.currency
                or not position.delisting_cash_source
            ):
                issues.append(
                    f"DELISTING_SETTLEMENT_MISSING:{position.symbol}:{months}M"
                )
                continue
            exit_date = position.delisted_on
            exit_value = position.delisting_cash_per_share
            exit_reason = "DELISTING_SETTLEMENT"
        else:
            exit_point = _exit_price(
                prices,
                target_date,
                currency=entry.currency,
            )
            if exit_point is None or exit_point.close_price is None:
                issues.append(
                    f"VERIFIED_ADJUSTED_EXIT_PRICE_MISSING:"
                    f"{position.symbol}:{months}M"
                )
                continue
            exit_date = exit_point.trade_date
            exit_value = exit_point.close_price

        if exit_date > data_end:
            issues.append(
                f"RESULT_OUTSIDE_DECLARED_DATA_PERIOD:"
                f"{position.symbol}:{months}M"
            )
        dividends = sum(
            (
                item.dps
                for item in _latest_dividends_available_by(
                    position,
                    entry_date=entry.trade_date,
                    exit_date=exit_date,
                    currency=entry.currency,
                )
            ),
            start=Decimal(0),
        )
        gross_return = (
            exit_value + dividends - entry.open_price
        ) / entry.open_price
        transaction_cost_return = (
            entry.open_price * cost_rate + exit_value * cost_rate
        ) / entry.open_price
        net_return = gross_return - transaction_cost_return
        benchmark_return = benchmark_returns.get(months)
        if benchmark_return is None:
            issues.append(f"PRIMARY_BENCHMARK_MISSING:{months}M")
            continue
        horizons.append(
            BacktestHorizonResult(
                months=months,
                exit_date=exit_date,
                exit_reason=exit_reason,
                exit_value_per_share=exit_value,
                dividend_per_share=dividends,
                gross_return=gross_return,
                transaction_cost_return=transaction_cost_return,
                net_return=net_return,
                benchmark_return=benchmark_return,
                excess_return=net_return - benchmark_return,
            )
        )
    if issues or len(horizons) != len(rules.horizon_months):
        return None, issues
    return (
        BacktestPositionResult(
            stock_id=position.stock_id,
            symbol=position.symbol,
            name=position.name,
            target_weight=position.target_weight,
            industry_code=position.industry_code,
            recommendation_category=position.recommendation_category,
            execution_date=entry.trade_date,
            execution_price=entry.open_price,
            currency=entry.currency,
            was_delisted=any(
                item.exit_reason == "DELISTING_SETTLEMENT"
                for item in horizons
            ),
            horizons=tuple(horizons),
        ),
        [],
    )


def _turnover(
    previous_weights: dict[str, Decimal],
    current_weights: dict[str, Decimal],
) -> Decimal:
    symbols = set(previous_weights) | set(current_weights)
    previous_cash = Decimal(1) - sum(
        previous_weights.values(),
        start=Decimal(0),
    )
    current_cash = Decimal(1) - sum(
        current_weights.values(),
        start=Decimal(0),
    )
    movement = sum(
        (
            abs(
                current_weights.get(symbol, Decimal(0))
                - previous_weights.get(symbol, Decimal(0))
            )
            for symbol in symbols
        ),
        start=Decimal(0),
    )
    return (movement + abs(current_cash - previous_cash)) / Decimal(2)


def evaluate_fold(
    fold: BacktestFoldInput,
    rules: BacktestRules,
    previous_weights: dict[str, Decimal],
    *,
    data_end: date,
) -> tuple[BacktestFoldResult | None, list[str], dict[str, Decimal]]:
    issues: list[str] = []
    if fold.universe_method != UniverseMethod.POINT_IN_TIME_HISTORY:
        issues.append("POINT_IN_TIME_UNIVERSE_REQUIRED")
    if not fold.universe_complete:
        issues.append("POINT_IN_TIME_UNIVERSE_INCOMPLETE")
    if not fold.includes_delisted:
        issues.append("DELISTED_UNIVERSE_NOT_VERIFIED")
    if not fold.universe_symbols:
        issues.append("POINT_IN_TIME_UNIVERSE_EMPTY")
    if not fold.positions:
        issues.append("NO_SELECTED_POSITIONS")

    (
        benchmark_returns,
        high_dividend_returns,
        benchmark_issues,
    ) = _benchmark_horizons(fold, rules, data_end=data_end)
    issues.extend(benchmark_issues)
    positions: list[BacktestPositionResult] = []
    for position in fold.positions:
        result, position_issues = _position_result(
            position,
            fold,
            rules,
            benchmark_returns,
            data_end=data_end,
        )
        issues.extend(position_issues)
        if result is not None:
            positions.append(result)
    if issues or len(positions) != len(fold.positions):
        return None, issues, previous_weights

    current_weights = {
        item.symbol: item.target_weight for item in fold.positions
    }
    portfolio_returns: dict[str, Decimal] = {}
    transaction_cost_returns: dict[str, Decimal] = {}
    excess_returns: dict[str, Decimal] = {}
    benchmark_result: dict[str, Decimal] = {}
    high_dividend_result: dict[str, Decimal] = {}
    for months in rules.horizon_months:
        label = horizon_label(months)
        portfolio_return = sum(
            (
                item.target_weight
                * next(
                    horizon.net_return
                    for horizon in item.horizons
                    if horizon.months == months
                )
                for item in positions
            ),
            start=Decimal(0),
        )
        transaction_cost = sum(
            (
                item.target_weight
                * next(
                    horizon.transaction_cost_return
                    for horizon in item.horizons
                    if horizon.months == months
                )
                for item in positions
            ),
            start=Decimal(0),
        )
        benchmark_return = benchmark_returns[months]
        portfolio_returns[label] = portfolio_return
        benchmark_result[label] = benchmark_return
        transaction_cost_returns[label] = transaction_cost
        excess_returns[label] = portfolio_return - benchmark_return
        high_dividend_return = high_dividend_returns.get(months)
        if high_dividend_return is not None:
            high_dividend_result[label] = high_dividend_return
    return (
        BacktestFoldResult(
            signal_date=fold.signal_at.date(),
            execution_date=min(item.execution_date for item in positions),
            universe_count=len(fold.universe_symbols),
            selected_count=len(positions),
            market_regime=fold.market_regime,
            turnover=_turnover(previous_weights, current_weights),
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_result,
            excess_returns=excess_returns,
            transaction_cost_returns=transaction_cost_returns,
            positions=tuple(positions),
            high_dividend_benchmark_returns=high_dividend_result,
        ),
        [],
        current_weights,
    )
