from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.analysis import Recommendation
from app.db.models.market import PriceDaily, Stock
from app.db.models.portfolio import (
    PortfolioAllocation,
    PortfolioPosition,
    PortfolioSetting,
    RecommendationReason,
    RecommendationRun,
    SplitBuyPlan,
)
from app.models.market_analysis import MarketRegime
from app.models.metadata import DataState, DataTiming
from app.models.recommendation import (
    HoldingAction,
    PortfolioProfile,
    PortfolioSleeve,
    RecommendationCategory,
    RecommendationDecision,
    RecommendationRunResult,
    SplitBuyPlanResult,
    SplitBuyStatus,
    SplitBuyTranche,
)
from app.utils.dates import now_kst, restore_database_kst


def _profile_hash(profile: PortfolioProfile) -> str:
    payload = json.dumps(
        profile.model_dump(
            mode="json",
            exclude_none=False,
            by_alias=True,
        ),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


class RecommendationRepository:
    def save_profile(
        self,
        session: Session,
        profile: PortfolioProfile,
        *,
        source: str,
    ) -> PortfolioSetting:
        profile_hash = _profile_hash(profile)
        existing = session.scalar(
            select(PortfolioSetting).where(
                PortfolioSetting.profile_hash == profile_hash
            )
        )
        selected_at = now_kst()
        if existing is not None:
            existing.selected_at = selected_at
            session.flush()
            return existing
        payload = profile.model_dump(mode="json")
        row = PortfolioSetting(
            selected_at=selected_at,
            profile_name=profile.profile_name,
            profile_hash=profile_hash,
            source=source,
            total_capital=profile.total_capital,
            current_cash=profile.current_cash,
            risk_profile=profile.risk_profile,
            target_dividend_yield=profile.target_dividend_yield,
            target_stock_count=profile.target_stock_count,
            max_dividend_stock_weight=profile.max_dividend_stock_weight,
            max_growth_stock_weight=profile.max_growth_stock_weight,
            max_industry_weight=profile.max_industry_weight,
            max_company_group_weight=profile.max_company_group_weight,
            include_preferred=profile.include_preferred,
            include_reits=profile.include_reits,
            minimum_trading_value=profile.minimum_trading_value,
            normal_target=payload["normal_target"],
            regime_targets=payload["regime_targets"],
            config_payload=payload,
        )
        session.add(row)
        session.flush()
        return row

    def latest_profile(
        self,
        session: Session,
    ) -> tuple[int, PortfolioProfile] | None:
        row = session.scalar(
            select(PortfolioSetting).order_by(
                PortfolioSetting.selected_at.desc(),
                PortfolioSetting.created_at.desc(),
                PortfolioSetting.id.desc(),
            )
        )
        if row is None:
            return None
        return row.id, PortfolioProfile.model_validate(row.config_payload)

    @staticmethod
    def universe(
        session: Session,
        *,
        as_of_at: datetime,
    ) -> list[Stock]:
        return list(
            session.scalars(
                select(Stock)
                .where(
                    Stock.is_active.is_(True),
                    Stock.is_kospi.is_(True),
                    Stock.data_state == DataState.AVAILABLE.value,
                    Stock.collected_at <= as_of_at,
                )
                .order_by(Stock.symbol)
            ).all()
        )

    @staticmethod
    def verified_reference_price(
        session: Session,
        stock_id: int,
        *,
        as_of_at: datetime,
        provider: str,
    ) -> PriceDaily | None:
        return session.scalar(
            select(PriceDaily)
            .where(
                PriceDaily.stock_id == stock_id,
                PriceDaily.trade_date <= as_of_at.date(),
                PriceDaily.collected_at <= as_of_at,
                PriceDaily.source_provider == provider,
                PriceDaily.is_adjusted.is_(True),
                PriceDaily.adjustment_status == "VERIFIED",
                PriceDaily.data_state == DataState.AVAILABLE.value,
                PriceDaily.data_timing == DataTiming.PREVIOUS_CLOSE.value,
                PriceDaily.close_price.is_not(None),
                PriceDaily.close_price > 0,
            )
            .order_by(
                PriceDaily.trade_date.desc(),
                PriceDaily.collected_at.desc(),
                PriceDaily.id.desc(),
            )
        )

    def save_run(
        self,
        session: Session,
        result: RecommendationRunResult,
        *,
        portfolio_setting_id: int,
        market_snapshot_id: int | None,
        source_snapshot_hashes: dict[str, object],
        explanation: str,
    ) -> RecommendationRun:
        existing = session.scalar(
            select(RecommendationRun).where(
                RecommendationRun.as_of_at == result.as_of_at,
                RecommendationRun.score_version == result.score_version,
                RecommendationRun.rule_version == result.rule_version,
                RecommendationRun.config_hash == result.config_hash,
                RecommendationRun.input_data_hash == result.input_data_hash,
            )
        )
        if existing is not None:
            return existing
        run = RecommendationRun(
            portfolio_setting_id=portfolio_setting_id,
            market_regime_snapshot_id=market_snapshot_id,
            analyzed_at=result.analyzed_at,
            as_of_at=result.as_of_at,
            data_basis_date=result.basis_date,
            status="COMPLETED",
            data_state=result.state.value,
            score_version=result.score_version,
            rule_version=result.rule_version,
            market_rule_version=result.market_rule_version,
            market_regime=result.market_regime.value,
            config_hash=result.config_hash,
            input_data_hash=result.input_data_hash,
            source_snapshot_hashes=source_snapshot_hashes,
            total_count=result.total_count,
            processed_count=result.processed_count,
            recommended_count=result.recommended_count,
            excluded_count=result.excluded_count,
            insufficient_count=result.insufficient_count,
            missing_core_data=list(result.missing_core_data),
            explanation=explanation,
        )
        session.add(run)
        session.flush()
        self._save_decisions(
            session,
            run,
            result.recommendations,
            market_snapshot_id=market_snapshot_id,
        )
        session.flush()
        return run

    def _save_decisions(
        self,
        session: Session,
        run: RecommendationRun,
        decisions: tuple[RecommendationDecision, ...],
        *,
        market_snapshot_id: int | None,
    ) -> None:
        for rank, item in enumerate(decisions, start=1):
            data_state = (
                DataState.MISSING.value
                if item.category == RecommendationCategory.INSUFFICIENT_DATA
                else DataState.AVAILABLE.value
            )
            reason_summary = " / ".join(
                (
                    *item.positive_reasons[:1],
                    *item.risk_reasons[:1],
                    *item.exclusion_reasons[:1],
                )
            )
            score_snapshot_id = item.raw_metrics.get("phase2_snapshot_id")
            if not isinstance(score_snapshot_id, int):
                score_snapshot_id = None
            recommendation = Recommendation(
                stock_id=item.stock_id,
                score_snapshot_id=score_snapshot_id,
                recommendation_run_id=run.id,
                market_regime_snapshot_id=market_snapshot_id,
                as_of_at=run.as_of_at,
                analyzed_at=run.analyzed_at,
                data_basis_date=run.data_basis_date,
                rank=rank,
                recommendation_type=item.category.value,
                recommendation_label=item.category_label,
                reason_summary=reason_summary or None,
                score_version=run.score_version,
                rule_version=run.rule_version,
                market_rule_version=run.market_rule_version,
                config_hash=run.config_hash,
                input_data_hash=run.input_data_hash,
                score_scope=item.score_scope,
                entry_score_scope=item.entry_score_scope,
                investment_score=item.investment_score,
                entry_score=item.entry_score,
                data_confidence=item.data_confidence,
                market_regime=item.market_regime.value,
                portfolio_sleeve=item.sleeve.value,
                industry_code=item.industry_code,
                company_group_code=item.company_group_code,
                company_group_check_state=item.company_group_check_state,
                target_weight=item.target_weight,
                initial_buy_weight=item.initial_buy_weight,
                holding_action=item.holding_action.value,
                raw_metrics=item.raw_metrics,
                filter_results=list(item.filter_results),
                positive_reasons=list(item.positive_reasons),
                risk_reasons=list(item.risk_reasons),
                exclusion_reasons=list(item.exclusion_reasons),
                missing_data=list(item.missing_data),
                data_state=data_state,
            )
            session.add(recommendation)
            session.flush()
            self._save_reasons(session, recommendation.id, item)
            if item.split_buy_plan is not None:
                plan = item.split_buy_plan
                session.add(
                    SplitBuyPlan(
                        recommendation_id=recommendation.id,
                        status=plan.status.value,
                        reference_price=plan.reference_price,
                        reference_price_date=plan.reference_price_date,
                        reference_price_provider=plan.reference_price_provider,
                        reference_price_currency=plan.reference_price_currency,
                        reference_price_collected_at=(
                            plan.reference_price_collected_at
                        ),
                        reference_price_timing=(
                            plan.reference_price_timing.value
                            if plan.reference_price_timing is not None
                            else None
                        ),
                        tranches=[
                            tranche.model_dump(mode="json") for tranche in plan.tranches
                        ],
                        cancellation_conditions=list(plan.cancellation_conditions),
                        is_order_executable=False,
                        explanation=plan.explanation,
                    )
                )
            if item.target_weight is not None and item.target_weight > 0:
                session.add(
                    PortfolioAllocation(
                        recommendation_run_id=run.id,
                        recommendation_id=recommendation.id,
                        stock_id=item.stock_id,
                        sleeve=item.sleeve.value,
                        target_weight=item.target_weight,
                        initial_buy_weight=item.initial_buy_weight or Decimal(0),
                        industry_code=item.industry_code,
                        company_group_code=item.company_group_code,
                        company_group_check_state=(item.company_group_check_state),
                        rationale=(
                            "설정된 종목·산업 한도와 시장국면별 "
                            "배당/성장 목표비중을 적용한 읽기 전용 목표입니다."
                        ),
                    )
                )

    @staticmethod
    def _save_reasons(
        session: Session,
        recommendation_id: int,
        item: RecommendationDecision,
    ) -> None:
        groups = (
            ("POSITIVE", item.positive_reasons),
            ("RISK", item.risk_reasons),
            ("EXCLUSION", item.exclusion_reasons),
            ("MISSING", item.missing_data),
        )
        for reason_type, reasons in groups:
            for sequence, reason in enumerate(reasons, start=1):
                session.add(
                    RecommendationReason(
                        recommendation_id=recommendation_id,
                        reason_type=reason_type,
                        sequence=sequence,
                        reason_code=(reason if reason_type == "MISSING" else None),
                        reason_text=reason,
                    )
                )

    def load_run(
        self,
        session: Session,
        run_id: int,
    ) -> RecommendationRunResult | None:
        run = session.get(RecommendationRun, run_id)
        if run is None:
            return None
        rows = session.scalars(
            select(Recommendation)
            .where(Recommendation.recommendation_run_id == run.id)
            .order_by(Recommendation.rank, Recommendation.id)
        ).all()
        decisions: list[RecommendationDecision] = []
        for row in rows:
            stock = session.get(Stock, row.stock_id)
            if stock is None:
                raise RuntimeError("recommendation refers to a missing stock")
            plan_row = session.scalar(
                select(SplitBuyPlan).where(SplitBuyPlan.recommendation_id == row.id)
            )
            plan = (
                SplitBuyPlanResult(
                    status=SplitBuyStatus(plan_row.status),
                    reference_price=plan_row.reference_price,
                    reference_price_date=plan_row.reference_price_date,
                    reference_price_provider=(plan_row.reference_price_provider),
                    reference_price_currency=(plan_row.reference_price_currency),
                    reference_price_collected_at=(
                        restore_database_kst(
                            plan_row.reference_price_collected_at
                        )
                        if plan_row.reference_price_collected_at is not None
                        else None
                    ),
                    reference_price_timing=(
                        DataTiming(plan_row.reference_price_timing)
                        if plan_row.reference_price_timing is not None
                        else None
                    ),
                    tranches=tuple(
                        SplitBuyTranche.model_validate(item)
                        for item in plan_row.tranches
                    ),
                    cancellation_conditions=tuple(plan_row.cancellation_conditions),
                    is_order_executable=plan_row.is_order_executable,
                    explanation=plan_row.explanation,
                )
                if plan_row is not None
                else None
            )
            decisions.append(
                RecommendationDecision(
                    stock_id=row.stock_id,
                    symbol=stock.symbol,
                    name=stock.name_ko,
                    category=RecommendationCategory(row.recommendation_type),
                    category_label=(
                        row.recommendation_label or row.recommendation_type
                    ),
                    score_scope=row.score_scope or "UNKNOWN",
                    investment_score=row.investment_score,
                    entry_score=row.entry_score,
                    entry_score_scope=row.entry_score_scope or "UNKNOWN",
                    data_confidence=row.data_confidence,
                    market_regime=MarketRegime(
                        row.market_regime or MarketRegime.UNCERTAIN.value
                    ),
                    sleeve=PortfolioSleeve(
                        row.portfolio_sleeve or PortfolioSleeve.UNCLASSIFIED.value
                    ),
                    industry_code=row.industry_code,
                    company_group_code=row.company_group_code,
                    company_group_check_state=(
                        row.company_group_check_state or "NOT_AVAILABLE"
                    ),
                    market_shock_discount_score=self._discount_from_raw(
                        row.raw_metrics
                    ),
                    target_weight=row.target_weight,
                    initial_buy_weight=row.initial_buy_weight,
                    holding_action=HoldingAction(
                        row.holding_action or HoldingAction.NOT_COMPUTABLE.value
                    ),
                    positive_reasons=tuple(row.positive_reasons or []),
                    risk_reasons=tuple(row.risk_reasons or []),
                    exclusion_reasons=tuple(row.exclusion_reasons or []),
                    missing_data=tuple(row.missing_data or []),
                    raw_metrics=row.raw_metrics or {},
                    filter_results=tuple(row.filter_results or []),
                    split_buy_plan=plan,
                )
            )
        return RecommendationRunResult(
            run_id=run.id,
            state=DataState(run.data_state),
            analyzed_at=restore_database_kst(run.analyzed_at),
            as_of_at=restore_database_kst(run.as_of_at),
            basis_date=run.data_basis_date,
            score_version=run.score_version,
            rule_version=run.rule_version,
            market_rule_version=run.market_rule_version,
            config_hash=run.config_hash,
            input_data_hash=run.input_data_hash,
            total_count=run.total_count,
            processed_count=run.processed_count,
            recommended_count=run.recommended_count,
            excluded_count=run.excluded_count,
            insufficient_count=run.insufficient_count,
            market_regime=MarketRegime(run.market_regime),
            missing_core_data=tuple(run.missing_core_data),
            recommendations=tuple(decisions),
        )

    def latest_run(
        self,
        session: Session,
    ) -> RecommendationRunResult | None:
        run_id = session.scalar(
            select(RecommendationRun.id).order_by(
                RecommendationRun.as_of_at.desc(),
                RecommendationRun.created_at.desc(),
                RecommendationRun.id.desc(),
            )
        )
        return self.load_run(session, run_id) if run_id is not None else None

    @staticmethod
    def _discount_from_raw(
        raw_metrics: dict[str, object] | None,
    ) -> Decimal | None:
        if not raw_metrics:
            return None
        value = raw_metrics.get("market_shock_discount_score")
        return Decimal(value) if isinstance(value, str) else None

    def save_position(
        self,
        session: Session,
        *,
        portfolio_setting_id: int,
        stock_id: int,
        quantity: Decimal,
        average_purchase_price: Decimal | None,
        currency: str | None,
        as_of_date: datetime,
    ) -> PortfolioPosition:
        row = session.scalar(
            select(PortfolioPosition).where(
                PortfolioPosition.portfolio_setting_id == portfolio_setting_id,
                PortfolioPosition.stock_id == stock_id,
            )
        )
        if row is None:
            row = PortfolioPosition(
                portfolio_setting_id=portfolio_setting_id,
                stock_id=stock_id,
                quantity=quantity,
                average_purchase_price=average_purchase_price,
                currency=currency,
                as_of_date=as_of_date.date(),
                source="USER_INPUT",
            )
            session.add(row)
        else:
            row.quantity = quantity
            row.average_purchase_price = average_purchase_price
            row.currency = currency
            row.as_of_date = as_of_date.date()
        session.flush()
        return row

    @staticmethod
    def positions(
        session: Session,
        portfolio_setting_id: int,
    ) -> list[tuple[PortfolioPosition, Stock]]:
        rows = session.execute(
            select(PortfolioPosition, Stock)
            .join(Stock, PortfolioPosition.stock_id == Stock.id)
            .where(PortfolioPosition.portfolio_setting_id == portfolio_setting_id)
            .order_by(Stock.symbol)
        ).all()
        return [(position, stock) for position, stock in rows]

    def copy_positions(
        self,
        session: Session,
        *,
        source_setting_id: int,
        target_setting_id: int,
    ) -> None:
        if source_setting_id == target_setting_id:
            return
        existing_stock_ids = set(
            session.scalars(
                select(PortfolioPosition.stock_id).where(
                    PortfolioPosition.portfolio_setting_id
                    == target_setting_id
                )
            ).all()
        )
        source_rows = session.scalars(
            select(PortfolioPosition).where(
                PortfolioPosition.portfolio_setting_id
                == source_setting_id
            )
        ).all()
        for row in source_rows:
            if row.stock_id in existing_stock_ids:
                continue
            session.add(
                PortfolioPosition(
                    portfolio_setting_id=target_setting_id,
                    stock_id=row.stock_id,
                    quantity=row.quantity,
                    average_purchase_price=row.average_purchase_price,
                    currency=row.currency,
                    as_of_date=row.as_of_date,
                    source=row.source,
                )
            )
