from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from app.models.backtest import (
    BacktestDataset,
    BacktestFoldResult,
    BacktestMetrics,
    BacktestRules,
    DividendPayment,
)
from app.services.backtest_execution import horizon_label


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, start=Decimal(0)) / Decimal(len(values))


def _product(values: Iterable[Decimal]) -> Decimal:
    result = Decimal(1)
    for value in values:
        result *= value
    return result


def _maximum_drawdown(returns: list[Decimal]) -> Decimal:
    equity = Decimal(1)
    peak = Decimal(1)
    drawdown = Decimal(0)
    for item in returns:
        equity *= Decimal(1) + item
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - Decimal(1))
    return drawdown


def _annualized_return(
    cumulative_return: Decimal,
    *,
    days: int,
) -> Decimal | None:
    total = Decimal(1) + cumulative_return
    if days <= 0 or total <= 0:
        return None
    return (
        (total.ln() * (Decimal(365) / Decimal(days))).exp()
        - Decimal(1)
    )


def _dispersion(
    returns: list[Decimal],
    *,
    periods_per_year: Decimal,
) -> tuple[Decimal | None, Decimal | None]:
    if len(returns) < 2:
        return None, None
    average = _mean(returns)
    variance = sum(
        ((item - average) ** 2 for item in returns),
        start=Decimal(0),
    ) / Decimal(len(returns))
    period_volatility = variance.sqrt()
    annualized_volatility = period_volatility * periods_per_year.sqrt()
    sharpe = (
        None
        if period_volatility == 0
        else average / period_volatility * periods_per_year.sqrt()
    )
    return annualized_volatility, sharpe


def _latest_payment(
    current: DividendPayment | None,
    candidate: DividendPayment,
) -> DividendPayment:
    if current is None or (
        candidate.filing_date,
        candidate.receipt_no,
    ) > (
        current.filing_date,
        current.receipt_no,
    ):
        return candidate
    return current


def _dividend_cut_ratio(dataset: BacktestDataset) -> Decimal | None:
    payments_by_symbol: dict[
        str,
        dict[tuple[date, str, str], DividendPayment],
    ] = defaultdict(dict)
    for fold in dataset.folds:
        for position in fold.positions:
            for item in position.dividends:
                if not (
                    item.is_confirmed
                    and not item.is_estimate
                    and item.filing_date <= dataset.end_date
                ):
                    continue
                event_receipt = (
                    item.correction_of_receipt_no or item.receipt_no
                )
                key = (item.payment_date, item.currency, event_receipt)
                payments_by_symbol[position.symbol][key] = _latest_payment(
                    payments_by_symbol[position.symbol].get(key),
                    item,
                )
    comparable = 0
    cuts = 0
    for payments in payments_by_symbol.values():
        annual_totals: dict[int, Decimal] = defaultdict(Decimal)
        for payment in payments.values():
            annual_totals[payment.business_year] += payment.dps
        ordered = [
            amount for _, amount in sorted(annual_totals.items())
        ]
        if len(ordered) < 2:
            continue
        comparable += 1
        if ordered[-1] < ordered[-2]:
            cuts += 1
    if comparable == 0:
        return None
    return Decimal(cuts) / Decimal(comparable)


def calculate_metrics(
    dataset: BacktestDataset,
    folds: tuple[BacktestFoldResult, ...],
    rules: BacktestRules,
) -> BacktestMetrics:
    primary = horizon_label(rules.primary_horizon_months)
    returns = [item.portfolio_returns[primary] for item in folds]
    benchmark_returns = [item.benchmark_returns[primary] for item in folds]
    cumulative = (
        _product(Decimal(1) + item for item in returns) - Decimal(1)
    )
    benchmark_cumulative = (
        _product(Decimal(1) + item for item in benchmark_returns)
        - Decimal(1)
    )
    high_dividend_cumulative: Decimal | None = None
    if rules.high_dividend_benchmark is not None:
        high_dividend_cumulative = (
            _product(
                Decimal(1)
                + item.high_dividend_benchmark_returns[primary]
                for item in folds
            )
            - Decimal(1)
        )
    last_exit = max(
        max(
            horizon.exit_date
            for position in fold.positions
            for horizon in position.horizons
            if horizon.months == rules.primary_horizon_months
        )
        for fold in folds
    )
    days = (last_exit - folds[0].execution_date).days
    periods_per_year = Decimal(12) / Decimal(
        rules.primary_horizon_months
    )
    volatility, sharpe = _dispersion(
        returns,
        periods_per_year=periods_per_year,
    )
    winners = [item for item in returns if item > 0]
    losers = [item for item in returns if item < 0]
    profit_loss_ratio = (
        None
        if not winners or not losers
        else _mean(winners) / abs(_mean(losers))
    )

    horizon_performance = {
        horizon_label(months): _mean(
            [
                fold.portfolio_returns[horizon_label(months)]
                for fold in folds
            ]
        )
        for months in rules.horizon_months
    }
    regimes: dict[str, list[Decimal]] = defaultdict(list)
    industries: dict[str, list[tuple[Decimal, Decimal]]] = defaultdict(list)
    for fold in folds:
        regimes[fold.market_regime].append(
            fold.portfolio_returns[primary]
        )
        for position in fold.positions:
            if position.industry_code is None:
                continue
            horizon = next(
                item
                for item in position.horizons
                if item.months == rules.primary_horizon_months
            )
            industries[position.industry_code].append(
                (position.target_weight * horizon.net_return, position.target_weight)
            )
    industry_performance = {
        code: (
            sum((item[0] for item in values), start=Decimal(0))
            / sum((item[1] for item in values), start=Decimal(0))
        )
        for code, values in industries.items()
    }
    return BacktestMetrics(
        cumulative_total_return=cumulative,
        annualized_return=_annualized_return(cumulative, days=days),
        benchmark_cumulative_return=benchmark_cumulative,
        benchmark_excess_return=cumulative - benchmark_cumulative,
        maximum_drawdown=_maximum_drawdown(returns),
        annualized_volatility=volatility,
        sharpe_ratio=sharpe,
        win_rate=Decimal(len(winners)) / Decimal(len(returns)),
        profit_loss_ratio=profit_loss_ratio,
        average_turnover=_mean([item.turnover for item in folds]),
        total_transaction_cost_return=sum(
            (
                item.transaction_cost_returns[primary]
                for item in folds
            ),
            start=Decimal(0),
        ),
        recommendation_horizon_performance=horizon_performance,
        market_regime_performance={
            regime: _mean(values) for regime, values in regimes.items()
        },
        industry_performance=industry_performance,
        dividend_cut_ratio=_dividend_cut_ratio(dataset),
        high_dividend_benchmark_cumulative_return=(
            high_dividend_cumulative
        ),
        high_dividend_benchmark_excess_return=(
            None
            if high_dividend_cumulative is None
            else cumulative - high_dividend_cumulative
        ),
    )
