from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.backtest import BacktestRun
from app.models.backtest import BacktestDataset, BacktestResult, BacktestRules


class BacktestRepository:
    @staticmethod
    def existing(
        session: Session,
        result: BacktestResult,
    ) -> BacktestResult | None:
        row = session.scalar(
            select(BacktestRun).where(
                BacktestRun.backtest_version == result.backtest_version,
                BacktestRun.rule_version == result.rule_version,
                BacktestRun.config_hash == result.config_hash,
                BacktestRun.input_data_hash == result.input_data_hash,
            )
        )
        return BacktestRepository._to_result(row)

    @staticmethod
    def save(
        session: Session,
        *,
        dataset: BacktestDataset,
        rules: BacktestRules,
        result: BacktestResult,
    ) -> BacktestResult:
        row = BacktestRun(
            analyzed_at=result.analyzed_at,
            start_date=result.start_date,
            end_date=result.end_date,
            data_state=result.state.value,
            confidence=result.confidence.value,
            backtest_version=result.backtest_version,
            rule_version=result.rule_version,
            config_hash=result.config_hash,
            input_data_hash=result.input_data_hash,
            score_versions=list(result.score_versions),
            recommendation_rule_versions=list(
                result.recommendation_rule_versions
            ),
            market_rule_versions=list(result.market_rule_versions),
            universe_construction_method=(
                result.universe_construction_method
            ),
            financial_availability_method=(
                result.financial_availability_method
            ),
            correction_availability_method=(
                result.correction_availability_method
            ),
            execution_price_method=result.execution_price_method,
            adjusted_price_source=result.adjusted_price_source,
            dividend_treatment_method=result.dividend_treatment_method,
            transaction_cost_bps=rules.transaction_cost_bps,
            transaction_cost_assumption=(
                result.transaction_cost_assumption
            ),
            benchmark_method=result.benchmark_method,
            walk_forward_method=result.walk_forward_method,
            known_survival_bias=list(result.known_survival_bias),
            missing_data=list(result.missing_data),
            config_payload=rules.model_dump(mode="json"),
            input_payload=dataset.model_dump(mode="json"),
            result_payload=result.model_dump(
                mode="json",
                exclude={"run_id"},
            ),
        )
        session.add(row)
        session.flush()
        return result.model_copy(update={"run_id": row.id})

    @staticmethod
    def latest(session: Session) -> BacktestResult | None:
        row = session.scalar(
            select(BacktestRun).order_by(
                BacktestRun.analyzed_at.desc(),
                BacktestRun.created_at.desc(),
                BacktestRun.id.desc(),
            )
        )
        return BacktestRepository._to_result(row)

    @staticmethod
    def _to_result(row: BacktestRun | None) -> BacktestResult | None:
        if row is None:
            return None
        result = BacktestResult.model_validate(row.result_payload)
        return result.model_copy(update={"run_id": row.id})
