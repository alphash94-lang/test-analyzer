from __future__ import annotations

from app.config import Settings
from app.db.session import (
    create_db_engine,
    create_session_factory,
    dispose_db_engine,
)
from app.models.backtest import BacktestDataset, BacktestResult, BacktestRules
from app.repositories.backtest_repository import BacktestRepository
from app.services.backtest_calculator import calculate_backtest


def backtest_rules_from_settings(settings: Settings) -> BacktestRules:
    return BacktestRules(
        backtest_version=settings.phase6_backtest_version,
        rule_version=settings.phase6_rule_version,
        transaction_cost_bps=settings.phase6_transaction_cost_bps,
        adjusted_price_provider=settings.phase6_adjusted_price_provider,
        primary_benchmark=settings.phase6_primary_benchmark,
        high_dividend_benchmark=settings.phase6_high_dividend_benchmark,
        primary_horizon_months=settings.phase6_primary_horizon_months,
        minimum_walk_forward_folds=(
            settings.phase6_minimum_walk_forward_folds
        ),
    )


class BacktestService:
    def __init__(self, settings: Settings) -> None:
        self._engine = create_db_engine(settings)
        self._sessions = create_session_factory(self._engine)
        self._rules = backtest_rules_from_settings(settings)
        self._repository = BacktestRepository()

    def run(self, dataset: BacktestDataset) -> BacktestResult:
        calculated = calculate_backtest(dataset, self._rules)
        with self._sessions.begin() as session:
            existing = self._repository.existing(session, calculated)
            if existing is not None:
                return existing
            return self._repository.save(
                session,
                dataset=dataset,
                rules=self._rules,
                result=calculated,
            )

    def latest(self) -> BacktestResult | None:
        with self._sessions() as session:
            return self._repository.latest(session)

    def close(self) -> None:
        dispose_db_engine(self._engine)
