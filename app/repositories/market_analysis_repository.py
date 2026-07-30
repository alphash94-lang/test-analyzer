from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.market_analysis import (
    MarketContributionRecord,
    MarketMetricRecord,
    MarketRegimeSnapshot,
)
from app.models.market_analysis import Phase3AnalysisResult


class MarketAnalysisRepository:
    def save(
        self,
        session: Session,
        result: Phase3AnalysisResult,
    ) -> MarketRegimeSnapshot:
        existing = session.scalar(
            select(MarketRegimeSnapshot).where(
                MarketRegimeSnapshot.as_of_at == result.as_of_at,
                MarketRegimeSnapshot.rule_version == result.rule_version,
                MarketRegimeSnapshot.input_data_hash == result.input_data_hash,
            )
        )
        if existing is not None:
            return existing
        snapshot = MarketRegimeSnapshot(
            as_of_at=result.as_of_at,
            rule_version=result.rule_version,
            input_data_hash=result.input_data_hash,
            data_state=result.state.value,
            shock_classification=result.shock_classification.value,
            market_regime=result.market_regime.value,
            data_confidence=result.data_confidence,
            proxy_kind=result.proxy_kind.value,
            semiconductor_recovery=result.semiconductor_recovery,
            kospi_recovery=result.kospi_recovery,
            non_semiconductor_breadth=result.non_semiconductor_breadth,
            dividend_relative_strength_recovery=(
                result.dividend_relative_strength_recovery
            ),
            missing_core_data=list(result.missing_core_data),
            explanation=result.explanation,
        )
        session.add(snapshot)
        session.flush()
        session.add_all(
            [
                MarketMetricRecord(
                    market_regime_snapshot_id=snapshot.id,
                    metric_code=metric.code,
                    metric_label=metric.label,
                    state=metric.state.value,
                    value=metric.value,
                    text_value=metric.text_value,
                    unit=metric.unit,
                    source_provider=metric.source_provider,
                    source_function=metric.source_function,
                    as_of_at=metric.as_of_at,
                    collected_at=metric.collected_at,
                    calculation_method=metric.calculation_method,
                    data_quality=metric.data_quality,
                    data_timing=metric.data_timing.value,
                    source_kind=metric.source_kind.value,
                    proxy_kind=metric.proxy_kind.value,
                )
                for metric in result.metrics
            ]
        )
        session.add_all(
            [
                MarketContributionRecord(
                    market_regime_snapshot_id=snapshot.id,
                    stock_id=contribution.stock_id,
                    symbol=contribution.symbol,
                    name=contribution.name,
                    return_rate=contribution.return_rate,
                    previous_weight=contribution.previous_weight,
                    contribution=contribution.contribution,
                    is_semiconductor=contribution.is_semiconductor,
                    source_provider=contribution.source_provider,
                    market_cap_source_provider=(
                        contribution.market_cap_source_provider
                    ),
                    classification_source=contribution.classification_source,
                    as_of_date=contribution.as_of_date,
                    collected_at=contribution.collected_at,
                    data_timing=contribution.data_timing.value,
                    calculation_method=contribution.calculation_method,
                    data_quality=contribution.data_quality,
                    source_kind=contribution.source_kind.value,
                    proxy_kind=contribution.proxy_kind.value,
                )
                for contribution in result.contributions
            ]
        )
        session.flush()
        return snapshot

    @staticmethod
    def latest(
        session: Session,
    ) -> tuple[
        MarketRegimeSnapshot | None,
        list[MarketMetricRecord],
        list[MarketContributionRecord],
    ]:
        snapshot = session.scalar(
            select(MarketRegimeSnapshot).order_by(
                MarketRegimeSnapshot.as_of_at.desc(),
                MarketRegimeSnapshot.created_at.desc(),
                MarketRegimeSnapshot.id.desc(),
            )
        )
        if snapshot is None:
            return None, [], []
        metrics = session.scalars(
            select(MarketMetricRecord)
            .where(MarketMetricRecord.market_regime_snapshot_id == snapshot.id)
            .order_by(MarketMetricRecord.id)
        ).all()
        contributions = session.scalars(
            select(MarketContributionRecord)
            .where(MarketContributionRecord.market_regime_snapshot_id == snapshot.id)
            .order_by(MarketContributionRecord.contribution)
        ).all()
        return snapshot, list(metrics), list(contributions)
