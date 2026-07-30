from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.analysis import (
    ForcedFilterResult,
    ScoreComponentRecord,
    ScoreSnapshot,
    ValuationComparisonRecord,
)
from app.db.models.market import Stock
from app.models.metadata import DataState
from app.models.scoring import (
    ComponentState,
    FilterResult,
    FilterState,
    IndustryComparison,
    Phase2Result,
    ScoreComponent,
)
from app.utils.dates import restore_database_kst


def _overall_filter_state(result: Phase2Result) -> str:
    states = {item.state for item in result.filters}
    if FilterState.FAIL in states:
        return FilterState.FAIL.value
    if FilterState.REVIEW_REQUIRED in states:
        return FilterState.REVIEW_REQUIRED.value
    if FilterState.MISSING in states:
        return FilterState.MISSING.value
    if states == {FilterState.PASS}:
        return FilterState.PASS.value
    return FilterState.NOT_APPLICABLE.value


class ScoringRepository:
    def save(
        self,
        session: Session,
        stock_id: int,
        result: Phase2Result,
    ) -> ScoreSnapshot:
        row = session.scalar(
            select(ScoreSnapshot).where(
                ScoreSnapshot.stock_id == stock_id,
                ScoreSnapshot.as_of_at == result.as_of_at,
                ScoreSnapshot.score_version == result.score_version,
                ScoreSnapshot.rule_version == result.rule_version,
                ScoreSnapshot.input_data_hash == result.input_data_hash,
            )
        )
        if row is not None:
            return row
        row = ScoreSnapshot(
            stock_id=stock_id,
            as_of_at=result.as_of_at,
            score_version=result.score_version,
            rule_version=result.rule_version,
            input_data_hash=result.input_data_hash,
            investment_score=result.investment_score,
            entry_score=result.entry_score,
            data_confidence=result.data_confidence,
            data_state=result.data_state.value,
            score_scope=result.score_scope,
            individual_entry_score=result.individual_entry_score,
            filter_state=_overall_filter_state(result),
            recommendation_computable=result.recommendation_computable,
            missing_core_data=list(result.missing_core_data),
            explanation=result.explanation,
        )
        session.add(row)
        session.flush()
        for item in result.filters:
            session.add(
                ForcedFilterResult(
                    score_snapshot_id=row.id,
                    filter_code=item.code,
                    filter_name=item.name,
                    state=item.state.value,
                    is_blocking=item.is_blocking,
                    reason=item.reason,
                    raw_value=item.raw_value,
                    raw_text=item.raw_text,
                    source_provider=item.source_provider,
                    evidence_date=item.evidence_date,
                )
            )
        for item in result.components:
            session.add(
                ScoreComponentRecord(
                    score_snapshot_id=row.id,
                    score_name=item.score_name,
                    component_code=item.code,
                    state=item.state.value,
                    raw_value=item.raw_value,
                    raw_text=item.raw_text,
                    normalized_value=item.normalized_value,
                    weight=item.weight,
                    contribution=item.contribution,
                    explanation=item.explanation,
                    source_kind=item.source_kind,
                )
            )
        for item in result.valuation_comparisons:
            session.add(
                ValuationComparisonRecord(
                    score_snapshot_id=row.id,
                    metric_code=item.metric_code,
                    state=item.state.value,
                    current_value=item.current_value,
                    industry_median=item.industry_median,
                    historical_median=item.historical_median,
                    industry_percentile=item.industry_percentile,
                    historical_percentile=item.historical_percentile,
                    comparison_level=item.comparison_level,
                    classification_code=item.classification_code,
                    sample_size=item.sample_size,
                    explanation=item.explanation,
                )
            )
        session.flush()
        return row

    def latest(
        self,
        session: Session,
        stock_id: int,
    ) -> Phase2Result | None:
        row = session.scalar(
            select(ScoreSnapshot)
            .where(
                ScoreSnapshot.stock_id == stock_id,
                ScoreSnapshot.score_scope == "PHASE2_CORE_ONLY",
            )
            .order_by(
                ScoreSnapshot.as_of_at.desc(),
                ScoreSnapshot.created_at.desc(),
                ScoreSnapshot.id.desc(),
            )
        )
        if row is None:
            return None
        if row.data_confidence is None:
            raise ValueError("Phase 2 score snapshot has missing data confidence")
        filters = session.scalars(
            select(ForcedFilterResult)
            .where(ForcedFilterResult.score_snapshot_id == row.id)
            .order_by(ForcedFilterResult.id)
        ).all()
        components = session.scalars(
            select(ScoreComponentRecord)
            .where(ScoreComponentRecord.score_snapshot_id == row.id)
            .order_by(ScoreComponentRecord.id)
        ).all()
        comparisons = session.scalars(
            select(ValuationComparisonRecord)
            .where(ValuationComparisonRecord.score_snapshot_id == row.id)
            .order_by(ValuationComparisonRecord.id)
        ).all()
        return Phase2Result(
            symbol=self._symbol(session, row.stock_id),
            as_of_at=restore_database_kst(row.as_of_at),
            score_version=row.score_version,
            rule_version=row.rule_version,
            input_data_hash=row.input_data_hash,
            score_scope=row.score_scope,
            filters=tuple(
                FilterResult(
                    code=item.filter_code,
                    name=item.filter_name,
                    state=FilterState(item.state),
                    is_blocking=item.is_blocking,
                    reason=item.reason,
                    raw_value=item.raw_value,
                    raw_text=item.raw_text,
                    source_provider=item.source_provider,
                    evidence_date=item.evidence_date,
                )
                for item in filters
            ),
            components=tuple(
                ScoreComponent(
                    score_name=item.score_name,
                    code=item.component_code,
                    state=ComponentState(item.state),
                    raw_value=item.raw_value,
                    raw_text=item.raw_text,
                    normalized_value=item.normalized_value,
                    weight=item.weight,
                    contribution=item.contribution,
                    explanation=item.explanation,
                    source_kind=item.source_kind,
                )
                for item in components
            ),
            valuation_comparisons=tuple(
                IndustryComparison(
                    metric_code=item.metric_code,
                    state=ComponentState(item.state),
                    current_value=item.current_value,
                    industry_median=item.industry_median,
                    historical_median=item.historical_median,
                    industry_percentile=item.industry_percentile,
                    historical_percentile=item.historical_percentile,
                    comparison_level=item.comparison_level,
                    classification_code=item.classification_code,
                    sample_size=item.sample_size,
                    explanation=item.explanation,
                )
                for item in comparisons
            ),
            investment_score=row.investment_score,
            entry_score=row.entry_score,
            individual_entry_score=row.individual_entry_score,
            data_confidence=row.data_confidence,
            recommendation_computable=row.recommendation_computable,
            missing_core_data=tuple(row.missing_core_data),
            explanation=row.explanation,
            data_state=DataState(row.data_state),
        )

    @staticmethod
    def _symbol(session: Session, stock_id: int) -> str:
        symbol = session.scalar(select(Stock.symbol).where(Stock.id == stock_id))
        if symbol is None:
            raise RuntimeError("score snapshot refers to a missing stock")
        return symbol
