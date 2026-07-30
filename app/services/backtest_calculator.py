from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.models.backtest import (
    BacktestConfidence,
    BacktestDataset,
    BacktestFoldResult,
    BacktestMetrics,
    BacktestResult,
    BacktestRules,
    UniverseMethod,
)
from app.models.metadata import DataState
from app.services.backtest_execution import canonical_hash, evaluate_fold
from app.services.backtest_metrics import calculate_metrics
from app.utils.dates import now_kst

_FINANCIAL_METHOD = "FILING_DATE_NEXT_TRADING_DAY"
_CORRECTION_METHOD = "CORRECTION_FILING_NEXT_TRADING_DAY_NO_RETROACTIVE"
_EXECUTION_METHOD = "SIGNAL_AFTER_NEXT_TRADING_DAY_ADJUSTED_OPEN"
_DIVIDEND_METHOD = (
    "CONFIRMED_CASH_DPS_LATEST_CORRECTION_AVAILABLE_BY_HORIZON_EXIT"
)
_WALK_FORWARD_METHOD = "CHRONOLOGICAL_NON_OVERLAPPING_PRIMARY_HORIZON"
_DRAWDOWN_METHOD = "WALK_FORWARD_PRIMARY_HORIZON_FOLD_ENDPOINTS"


def _latest_input_collection(
    dataset: BacktestDataset,
) -> datetime | None:
    timestamps = [
        observation.collected_at
        for fold in dataset.folds
        for position in fold.positions
        for observation in position.prices
    ] + [
        observation.collected_at
        for fold in dataset.folds
        for observations in fold.benchmarks.values()
        for observation in observations
    ]
    return max(timestamps, default=None)


def _result(
    dataset: BacktestDataset,
    rules: BacktestRules,
    *,
    state: DataState,
    missing_data: tuple[str, ...],
    folds: tuple[BacktestFoldResult, ...],
    metrics: BacktestMetrics | None,
    config_hash: str,
    input_data_hash: str,
) -> BacktestResult:
    score_versions = tuple(
        sorted({item.score_version for item in dataset.folds})
    )
    recommendation_versions = tuple(
        sorted(
            {
                item.recommendation_rule_version
                for item in dataset.folds
            }
        )
    )
    market_versions = tuple(
        sorted({item.market_rule_version for item in dataset.folds})
    )
    universe_methods = tuple(
        sorted({item.universe_method.value for item in dataset.folds})
    )
    universe_method = (
        UniverseMethod.UNKNOWN.value
        if not universe_methods
        else universe_methods[0]
        if len(universe_methods) == 1
        else f"MIXED:{','.join(universe_methods)}"
    )
    confidence = (
        BacktestConfidence.UNAVAILABLE
        if state != DataState.AVAILABLE
        else BacktestConfidence.MEDIUM
        if dataset.known_survival_bias
        else BacktestConfidence.HIGH
    )
    benchmark_names = rules.primary_benchmark
    if rules.high_dividend_benchmark is not None:
        benchmark_names += f" 및 {rules.high_dividend_benchmark}"
    return BacktestResult(
        analyzed_at=now_kst(),
        state=state,
        confidence=confidence,
        start_date=dataset.start_date,
        end_date=dataset.end_date,
        backtest_version=rules.backtest_version,
        rule_version=rules.rule_version,
        config_hash=config_hash,
        input_data_hash=input_data_hash,
        score_versions=score_versions,
        recommendation_rule_versions=recommendation_versions,
        market_rule_versions=market_versions,
        universe_construction_method=universe_method,
        financial_availability_method=_FINANCIAL_METHOD,
        correction_availability_method=_CORRECTION_METHOD,
        execution_price_method=_EXECUTION_METHOD,
        adjusted_price_source=rules.adjusted_price_provider,
        dividend_treatment_method=_DIVIDEND_METHOD,
        transaction_cost_assumption=(
            f"매수·매도 각각 {rules.transaction_cost_bps}bp"
        ),
        benchmark_method=(
            f"{benchmark_names} 다음 거래일 시가~기간말 종가"
        ),
        walk_forward_method=_WALK_FORWARD_METHOD,
        known_survival_bias=dataset.known_survival_bias,
        missing_data=missing_data,
        folds=folds,
        metrics=metrics,
        input_source_name=dataset.source_name,
        latest_input_collected_at=_latest_input_collection(dataset),
        drawdown_method=_DRAWDOWN_METHOD,
    )


def _version_issues(dataset: BacktestDataset) -> list[str]:
    issues: list[str] = []
    if len({item.score_version for item in dataset.folds}) > 1:
        issues.append("SCORE_VERSION_CHANGED_INSIDE_BACKTEST")
    if (
        len(
            {
                item.recommendation_rule_version
                for item in dataset.folds
            }
        )
        > 1
    ):
        issues.append("RECOMMENDATION_RULE_CHANGED_INSIDE_BACKTEST")
    if len({item.market_rule_version for item in dataset.folds}) > 1:
        issues.append("MARKET_RULE_CHANGED_INSIDE_BACKTEST")
    if len(
        {item.recommendation_config_hash for item in dataset.folds}
    ) > 1:
        issues.append("RECOMMENDATION_CONFIG_CHANGED_INSIDE_BACKTEST")
    return issues


def _overlap_issues(
    folds: list[BacktestFoldResult],
    *,
    primary_horizon_months: int,
) -> list[str]:
    issues: list[str] = []
    previous_exit: date | None = None
    for fold in folds:
        primary_exit = max(
            next(
                item.exit_date
                for item in position.horizons
                if item.months == primary_horizon_months
            )
            for position in fold.positions
        )
        if previous_exit is not None and fold.signal_date < previous_exit:
            issues.append("PRIMARY_HORIZON_FOLDS_OVERLAP")
        previous_exit = primary_exit
    return issues


def calculate_backtest(
    dataset: BacktestDataset,
    rules: BacktestRules,
) -> BacktestResult:
    config_payload = rules.model_dump(mode="json")
    input_payload = dataset.model_dump(mode="json")
    config_hash = canonical_hash(config_payload)
    input_data_hash = canonical_hash(
        {
            "dataset": input_payload,
            "config_hash": config_hash,
            "backtest_version": rules.backtest_version,
            "rule_version": rules.rule_version,
        }
    )
    issues: list[str] = []
    if not dataset.folds:
        issues.append("POINT_IN_TIME_DATASET_MISSING")
    if len(dataset.folds) < rules.minimum_walk_forward_folds:
        issues.append("WALK_FORWARD_FOLDS_INSUFFICIENT")
    issues.extend(_version_issues(dataset))
    if issues:
        return _result(
            dataset,
            rules,
            state=DataState.MISSING,
            missing_data=tuple(dict.fromkeys(issues)),
            folds=(),
            metrics=None,
            config_hash=config_hash,
            input_data_hash=input_data_hash,
        )

    fold_results: list[BacktestFoldResult] = []
    previous_weights: dict[str, Decimal] = {}
    for fold in dataset.folds:
        fold_result, fold_issues, previous_weights = evaluate_fold(
            fold,
            rules,
            previous_weights,
            data_end=dataset.end_date,
        )
        issues.extend(fold_issues)
        if fold_result is not None:
            fold_results.append(fold_result)
    if issues or len(fold_results) != len(dataset.folds):
        return _result(
            dataset,
            rules,
            state=DataState.MISSING,
            missing_data=tuple(dict.fromkeys(issues)),
            folds=(),
            metrics=None,
            config_hash=config_hash,
            input_data_hash=input_data_hash,
        )

    issues.extend(
        _overlap_issues(
            fold_results,
            primary_horizon_months=rules.primary_horizon_months,
        )
    )
    if issues:
        return _result(
            dataset,
            rules,
            state=DataState.MISSING,
            missing_data=tuple(dict.fromkeys(issues)),
            folds=(),
            metrics=None,
            config_hash=config_hash,
            input_data_hash=input_data_hash,
        )

    completed_folds = tuple(fold_results)
    return _result(
        dataset,
        rules,
        state=DataState.AVAILABLE,
        missing_data=(),
        folds=completed_folds,
        metrics=calculate_metrics(dataset, completed_folds, rules),
        config_hash=config_hash,
        input_data_hash=input_data_hash,
    )
