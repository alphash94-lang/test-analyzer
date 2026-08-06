from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from hashlib import sha256

from sqlalchemy import select

from app.config import Settings
from app.db.models.market import Stock
from app.db.models.market_analysis import MarketRegimeSnapshot
from app.db.session import (
    create_db_engine,
    create_session_factory,
    dispose_db_engine,
)
from app.models.market_analysis import Phase3AnalysisResult
from app.models.metadata import DataState, DataTiming
from app.models.recommendation import (
    HoldingAction,
    MarketRecommendationContext,
    PortfolioProfile,
    PortfolioSleeve,
    RecommendationCategory,
    RecommendationDecision,
    RecommendationInput,
    RecommendationRunResult,
)
from app.repositories.recommendation_repository import (
    RecommendationRepository,
)
from app.repositories.scoring_repository import ScoringRepository
from app.services.market_regime_service import MarketRegimeService
from app.services.market_screening_service import (
    SCREEN_RULE_VERSION,
    SCREEN_SCORE_SCOPE,
    SCREEN_SCORE_VERSION,
    MarketScreeningService,
)
from app.services.phase2_input_service import Phase2InputAssembler
from app.services.portfolio_service import (
    allocate_portfolio,
    attach_split_buy_plans,
    default_portfolio_profile,
    phase4_rules_from_settings,
)
from app.services.recommendation_rules import evaluate_recommendation
from app.services.score_component_common import quantize_score
from app.services.scoring_rules import phase2_rules_from_settings
from app.services.scoring_service import evaluate_phase2
from app.utils.dates import ensure_kst, now_kst, restore_database_kst

ProgressCallback = Callable[[int, int, str, str, str], None]


def _canonical_hash(payload: object) -> str:
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _decision_sort_key(
    item: RecommendationDecision,
) -> tuple[int, Decimal, Decimal, Decimal, str]:
    priority = {
        RecommendationCategory.READY_FOR_RECOVERY: 0,
        RecommendationCategory.QUALITY_WAIT: 1,
        RecommendationCategory.EXCESSIVE_DISCOUNT: 2,
        RecommendationCategory.GENERAL_REVIEW: 3,
        RecommendationCategory.EXCLUDED: 4,
        RecommendationCategory.INSUFFICIENT_DATA: 5,
    }[item.category]
    return (
        priority,
        -(item.investment_score or Decimal(-1)),
        -(item.entry_score or Decimal(-1)),
        -(item.data_confidence or Decimal(-1)),
        item.symbol,
    )


class RecommendationService:
    def __init__(
        self,
        settings: Settings,
        *,
        repository: RecommendationRepository | None = None,
        assembler: Phase2InputAssembler | None = None,
        scoring_repository: ScoringRepository | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository or RecommendationRepository()
        self._assembler = assembler or Phase2InputAssembler()
        self._scoring = scoring_repository or ScoringRepository()
        self._phase2_rules = phase2_rules_from_settings(settings)
        self._phase4_rules = phase4_rules_from_settings(settings)
        self._engine = create_db_engine(settings)
        self._sessions = create_session_factory(self._engine)

    def run_universe(
        self,
        *,
        as_of_at: datetime,
        profile: PortfolioProfile | None = None,
        progress: ProgressCallback | None = None,
    ) -> RecommendationRunResult:
        normalized_as_of = ensure_kst(as_of_at)
        selected_profile = profile or self._latest_or_default_profile()
        market_service = MarketRegimeService(self._settings)
        try:
            market_result = market_service.analyze_and_store(
                as_of_date=normalized_as_of.date(),
                as_of_at=normalized_as_of,
            )
        finally:
            market_service.close()

        with self._sessions.begin() as session:
            profile_row = self._repository.save_profile(
                session,
                selected_profile,
                source=("USER_INPUT" if profile is not None else "CONFIG_DEFAULT"),
            )
            market_snapshot = session.scalar(
                select(MarketRegimeSnapshot).where(
                    MarketRegimeSnapshot.as_of_at == market_result.as_of_at,
                    MarketRegimeSnapshot.rule_version == market_result.rule_version,
                    MarketRegimeSnapshot.input_data_hash
                    == market_result.input_data_hash,
                )
            )
            market_context = self._market_context(
                market_result,
                market_snapshot.id if market_snapshot is not None else None,
            )
            stocks = self._repository.universe(
                session,
                as_of_at=normalized_as_of,
            )
            screening = MarketScreeningService().build(
                session,
                stocks,
                as_of_at=normalized_as_of,
            )
            reference_prices = self._repository.verified_reference_prices(
                session,
                [stock.id for stock in stocks],
                as_of_at=normalized_as_of,
                provider=self._settings.phase3_adjusted_price_provider,
            )
            total = len(stocks)
            order_amount = self._planned_order_amount(selected_profile)
            inputs: dict[int, RecommendationInput] = {}
            decisions: list[RecommendationDecision] = []
            semiconductor_by_stock = {
                item.stock_id: item.is_semiconductor
                for item in market_result.contributions
            }
            return_by_stock = {
                item.stock_id: item.return_rate
                for item in market_result.contributions
            }
            market_reference_return = self._market_reference_return(
                market_result
            )
            for processed, stock in enumerate(stocks, start=1):
                evidence = self._assembler.assemble(
                    session,
                    stock,
                    as_of_at=normalized_as_of,
                    rules=self._phase2_rules,
                    planned_order_amount=order_amount,
                )
                phase2_result = evaluate_phase2(
                    evidence,
                    self._phase2_rules,
                )
                strict_phase2 = phase2_result
                screen = screening[stock.id]
                phase2_result = phase2_result.model_copy(
                    update={
                        "score_version": SCREEN_SCORE_VERSION,
                        "rule_version": SCREEN_RULE_VERSION,
                        "input_data_hash": screen.input_data_hash,
                        "score_scope": SCREEN_SCORE_SCOPE,
                        "components": screen.components,
                        "valuation_comparisons": (),
                        "investment_score": screen.investment_score,
                        "individual_entry_score": (
                            screen.individual_entry_score
                        ),
                        "data_confidence": screen.data_confidence,
                        "recommendation_computable": True,
                        "missing_core_data": (),
                        "explanation": screen.explanation,
                        "data_state": DataState.AVAILABLE,
                    }
                )
                score_row = self._scoring.save(
                    session,
                    stock.id,
                    phase2_result,
                )
                price = reference_prices.get(stock.id)
                recommendation_input = RecommendationInput(
                    stock_id=stock.id,
                    symbol=stock.symbol,
                    name=stock.name_ko,
                    phase2_snapshot_id=score_row.id,
                    phase2=phase2_result,
                    market=market_context,
                    industry_code=screen.industry_code,
                    is_semiconductor=semiconductor_by_stock.get(stock.id),
                    reference_price=(price.close_price if price is not None else None),
                    reference_price_date=(
                        price.trade_date if price is not None else None
                    ),
                    reference_price_provider=(
                        price.source_provider if price is not None else None
                    ),
                    reference_price_currency=(
                        price.currency if price is not None else None
                    ),
                    reference_price_collected_at=(
                        restore_database_kst(price.collected_at)
                        if price is not None
                        else None
                    ),
                    reference_price_timing=(
                        DataTiming(price.data_timing)
                        if price is not None
                        else None
                    ),
                    market_relative_return_gap=(
                        market_reference_return - return_by_stock[stock.id]
                        if market_reference_return is not None
                        and stock.id in return_by_stock
                        and semiconductor_by_stock.get(stock.id) is False
                        else None
                    ),
                    market_shock_discount_score=(
                        self._discount_score(
                            market_reference_return
                            - return_by_stock[stock.id]
                        )
                        if market_reference_return is not None
                        and stock.id in return_by_stock
                        and semiconductor_by_stock.get(stock.id) is False
                        else None
                    ),
                )
                decision = evaluate_recommendation(
                    recommendation_input,
                    self._phase4_rules,
                )
                raw_metrics = dict(decision.raw_metrics)
                raw_metrics["phase2_snapshot_id"] = score_row.id
                raw_metrics["strict_phase2_investment_score"] = (
                    str(strict_phase2.investment_score)
                    if strict_phase2.investment_score is not None
                    else None
                )
                raw_metrics["screening_explanation"] = screen.explanation
                decision = decision.model_copy(update={"raw_metrics": raw_metrics})
                inputs[stock.id] = recommendation_input
                decisions.append(decision)
                if progress is not None:
                    progress(
                        processed,
                        total,
                        stock.symbol,
                        stock.name_ko,
                        decision.category.value,
                    )

            allocated = allocate_portfolio(
                tuple(decisions),
                selected_profile,
                market_result.market_regime,
                self._phase4_rules,
            )
            planned = attach_split_buy_plans(
                allocated,
                inputs,
                self._phase4_rules,
            )
            ordered = tuple(sorted(planned, key=_decision_sort_key))
            config_payload = {
                "phase4_rules": self._phase4_rules.model_dump(mode="json"),
                "portfolio_profile": selected_profile.model_dump(mode="json"),
            }
            config_hash = _canonical_hash(config_payload)
            source_snapshot_hashes = {
                "market": {
                    "snapshot_id": (
                        market_snapshot.id if market_snapshot is not None else None
                    ),
                    "rule_version": market_result.rule_version,
                    "input_data_hash": market_result.input_data_hash,
                },
                "phase2": [
                    self._phase2_source_snapshot(item)
                    for item in sorted(
                        inputs.values(),
                        key=lambda value: value.symbol,
                    )
                ],
            }
            input_hash = _canonical_hash(source_snapshot_hashes)
            missing = list(market_result.missing_core_data)
            recommended_count = sum(
                item.category
                in {
                    RecommendationCategory.READY_FOR_RECOVERY,
                    RecommendationCategory.QUALITY_WAIT,
                    RecommendationCategory.EXCESSIVE_DISCOUNT,
                    RecommendationCategory.GENERAL_REVIEW,
                }
                for item in ordered
            )
            excluded_count = sum(
                item.category == RecommendationCategory.EXCLUDED for item in ordered
            )
            insufficient_count = sum(
                item.category == RecommendationCategory.INSUFFICIENT_DATA
                for item in ordered
            )
            state, missing = self._run_state(
                total=total,
                insufficient_count=insufficient_count,
                market_state=market_result.state,
                market_missing=tuple(missing),
            )
            analyzed_at = now_kst()
            result = RecommendationRunResult(
                state=state,
                analyzed_at=analyzed_at,
                as_of_at=normalized_as_of,
                basis_date=normalized_as_of.date(),
                score_version=self._phase4_rules.score_version,
                rule_version=self._phase4_rules.rule_version,
                market_rule_version=market_result.rule_version,
                config_hash=config_hash,
                input_data_hash=input_hash,
                total_count=total,
                processed_count=total,
                recommended_count=recommended_count,
                excluded_count=excluded_count,
                insufficient_count=insufficient_count,
                market_regime=market_result.market_regime,
                missing_core_data=tuple(dict.fromkeys(missing)),
                recommendations=ordered,
            )
            explanation = (
                "핵심 데이터가 부족해 추천 또는 포트폴리오 목표를 "
                "확정하지 않았습니다: " + ", ".join(result.missing_core_data)
                if result.missing_core_data
                else (
                    "동일 데이터 스냅샷·config·score/rule version으로 "
                    "강제필터, 점수, 시장국면과 투자한도를 적용했습니다. "
                    "모든 결과는 읽기 전용입니다."
                )
            )
            run = self._repository.save_run(
                session,
                result,
                portfolio_setting_id=profile_row.id,
                market_snapshot_id=(
                    market_snapshot.id if market_snapshot is not None else None
                ),
                source_snapshot_hashes=source_snapshot_hashes,
                explanation=explanation,
            )
            stored = self._repository.load_run(session, run.id)
            if stored is None:
                raise RuntimeError("saved recommendation run was not found")
            return stored

    def latest(self) -> RecommendationRunResult | None:
        with self._sessions() as session:
            return self._repository.latest_run(session)

    def latest_profile(self) -> PortfolioProfile:
        return self._latest_or_default_profile()

    def save_profile(self, profile: PortfolioProfile) -> int:
        with self._sessions.begin() as session:
            previous = self._repository.latest_profile(session)
            row = self._repository.save_profile(
                session,
                profile,
                source="USER_INPUT",
            )
            if previous is not None:
                self._repository.copy_positions(
                    session,
                    source_setting_id=previous[0],
                    target_setting_id=row.id,
                )
            return row.id

    def save_position(
        self,
        *,
        symbol: str,
        quantity: Decimal,
        average_purchase_price: Decimal | None,
        as_of_at: datetime,
        currency: str | None = "KRW",
    ) -> bool:
        normalized_as_of = ensure_kst(as_of_at)
        with self._sessions.begin() as session:
            profile = self._repository.latest_profile(session)
            stock = session.scalar(
                select(Stock).where(
                    Stock.symbol == symbol,
                    Stock.is_active.is_(True),
                )
            )
            if profile is None or stock is None:
                return False
            profile_id, _ = profile
            self._repository.save_position(
                session,
                portfolio_setting_id=profile_id,
                stock_id=stock.id,
                quantity=quantity,
                average_purchase_price=average_purchase_price,
                currency=currency,
                as_of_date=normalized_as_of,
            )
            return True

    def positions(
        self,
        *,
        latest: RecommendationRunResult | None = None,
    ) -> list[dict[str, object]]:
        with self._sessions() as session:
            profile = self._repository.latest_profile(session)
            if profile is None:
                return []
            profile_id, profile_value = profile
            selected_latest = (
                latest
                if latest is not None
                else self._repository.latest_run(session)
            )
            recommendations = (
                {
                    item.stock_id: item
                    for item in selected_latest.recommendations
                }
                if selected_latest is not None
                else {}
            )
            position_rows = self._repository.positions(
                session,
                profile_id,
            )
            prices = (
                self._repository.verified_reference_prices(
                    session,
                    [stock.id for _, stock in position_rows],
                    as_of_at=selected_latest.as_of_at,
                    provider=self._settings.phase3_adjusted_price_provider,
                )
                if selected_latest is not None
                else {}
            )
            results: list[dict[str, object]] = []
            for position, stock in position_rows:
                recommendation = recommendations.get(stock.id)
                price = prices.get(stock.id)
                position_currency = (
                    position.currency.strip().upper()
                    if position.currency is not None
                    and position.currency.strip()
                    else None
                )
                price_currency = (
                    price.currency.strip().upper()
                    if price is not None
                    and price.currency is not None
                    and price.currency.strip()
                    else None
                )
                currencies_match = (
                    position_currency is not None
                    and price_currency is not None
                    and position_currency == price_currency
                )
                current_value = (
                    position.quantity * price.close_price
                    if price is not None
                    and price.close_price is not None
                    and currencies_match
                    else None
                )
                current_weight = (
                    current_value / profile_value.total_capital
                    if current_value is not None
                    and profile_value.total_capital is not None
                    and profile_value.total_capital > 0
                    else None
                )
                stock_cap = (
                    profile_value.max_growth_stock_weight
                    if recommendation is not None
                    and recommendation.sleeve == PortfolioSleeve.GROWTH
                    else profile_value.max_dividend_stock_weight
                )
                if (
                    recommendation is not None
                    and recommendation.category
                    == RecommendationCategory.EXCLUDED
                ):
                    action = HoldingAction.IMMEDIATE_REVIEW
                    action_reason = "저장된 강제필터·점수 판정이 투자배제입니다."
                elif recommendation is None:
                    action = HoldingAction.NOT_COMPUTABLE
                    action_reason = "동일 기준일 추천 스냅샷이 없습니다."
                elif current_weight is None:
                    action = HoldingAction.NOT_COMPUTABLE
                    if price is None:
                        action_reason = (
                            "동일 기준일의 검증된 수정종가가 없어 "
                            "현재 비중을 계산할 수 없습니다."
                        )
                    elif position_currency is None or price_currency is None:
                        action_reason = (
                            "보유종목 또는 검증된 수정종가의 통화가 없어 "
                            "현재 비중을 계산할 수 없습니다."
                        )
                    elif not currencies_match:
                        action_reason = (
                            f"보유종목 통화 {position_currency}와 가격 통화 "
                            f"{price_currency}가 달라 현재 비중을 계산할 수 없습니다."
                        )
                    else:
                        action_reason = (
                            "총 투자 가능자금이 없어 현재 비중을 "
                            "계산할 수 없습니다."
                        )
                elif current_weight > stock_cap:
                    action = HoldingAction.REDUCE_REVIEW
                    action_reason = (
                        f"현재 계산 비중 {current_weight:.4f}가 전략군 종목 "
                        f"한도 {stock_cap:.4f}를 초과합니다."
                    )
                else:
                    action = recommendation.holding_action
                    action_reason = (
                        "현재 계산 비중이 전략군 종목 한도 이내이며 "
                        "최신 추천 판정을 함께 적용했습니다."
                    )
                results.append(
                    {
                        "symbol": stock.symbol,
                        "name": stock.name_ko,
                        "quantity": position.quantity,
                        "average_purchase_price": (
                            position.average_purchase_price
                        ),
                        "currency": position.currency,
                        "as_of_date": position.as_of_date,
                        "reference_price": (
                            price.close_price if price is not None else None
                        ),
                        "reference_price_date": (
                            price.trade_date if price is not None else None
                        ),
                        "reference_price_provider": (
                            price.source_provider if price is not None else None
                        ),
                        "reference_price_currency": price_currency,
                        "reference_price_collected_at": (
                            restore_database_kst(price.collected_at)
                            if price is not None
                            else None
                        ),
                        "reference_price_timing": (
                            price.data_timing if price is not None else None
                        ),
                        "current_weight": current_weight,
                        "holding_action": action.value,
                        "holding_reason": action_reason,
                    }
                )
            return results

    def _latest_or_default_profile(self) -> PortfolioProfile:
        with self._sessions() as session:
            latest = self._repository.latest_profile(session)
            return (
                latest[1]
                if latest is not None
                else default_portfolio_profile(self._settings)
            )

    def _planned_order_amount(
        self,
        profile: PortfolioProfile,
    ) -> Decimal:
        if profile.total_capital is not None and profile.total_capital > 0:
            stock_cap = max(
                profile.max_dividend_stock_weight,
                profile.max_growth_stock_weight,
            )
            return (
                profile.total_capital
                * stock_cap
                * self._phase4_rules.tranche_weights[0]
            )
        return (
            self._settings.phase2_planned_order_amount_krw
            or Decimal(1_000_000)
        )

    @staticmethod
    def _market_context(
        result: Phase3AnalysisResult,
        snapshot_id: int | None,
    ) -> MarketRecommendationContext:
        return MarketRecommendationContext(
            snapshot_id=snapshot_id,
            as_of_at=result.as_of_at,
            rule_version=result.rule_version,
            input_data_hash=result.input_data_hash,
            state=result.state,
            shock_classification=result.shock_classification,
            market_regime=result.market_regime,
            data_confidence=result.data_confidence,
            semiconductor_recovery=result.semiconductor_recovery,
            kospi_recovery=result.kospi_recovery,
            non_semiconductor_breadth=result.non_semiconductor_breadth,
            dividend_relative_strength_recovery=(
                result.dividend_relative_strength_recovery
            ),
            missing_core_data=result.missing_core_data,
        )

    @staticmethod
    def _phase2_source_snapshot(
        item: RecommendationInput,
    ) -> dict[str, object]:
        return {
            "stock_id": item.stock_id,
            "symbol": item.symbol,
            "snapshot_id": item.phase2_snapshot_id,
            "score_version": item.phase2.score_version,
            "rule_version": item.phase2.rule_version,
            "input_data_hash": item.phase2.input_data_hash,
            "reference_price": (
                str(item.reference_price)
                if item.reference_price is not None
                else None
            ),
            "reference_price_date": (
                item.reference_price_date.isoformat()
                if item.reference_price_date is not None
                else None
            ),
            "reference_price_provider": item.reference_price_provider,
            "reference_price_currency": item.reference_price_currency,
            "reference_price_collected_at": (
                item.reference_price_collected_at.isoformat()
                if item.reference_price_collected_at is not None
                else None
            ),
            "reference_price_timing": (
                item.reference_price_timing.value
                if item.reference_price_timing is not None
                else None
            ),
        }

    @staticmethod
    def _run_state(
        *,
        total: int,
        insufficient_count: int,
        market_state: DataState,
        market_missing: tuple[str, ...],
    ) -> tuple[DataState, list[str]]:
        missing = list(market_missing)
        if total == 0:
            missing.append("ACTIVE_KOSPI_UNIVERSE")
        if total > 0 and insufficient_count == total:
            missing.append("ALL_STOCKS_INSUFFICIENT_DATA")
        state = (
            DataState.AVAILABLE
            if total > 0
            and insufficient_count < total
            and market_state == DataState.AVAILABLE
            else DataState.MISSING
        )
        return state, list(dict.fromkeys(missing))

    @staticmethod
    def _market_reference_return(
        result: Phase3AnalysisResult,
    ) -> Decimal | None:
        available = {
            metric.code: metric.value
            for metric in result.metrics
            if metric.state == DataState.AVAILABLE
            and metric.value is not None
        }
        non_semiconductor = available.get(
            "NON_SEMICONDUCTOR_EQUAL_RETURN"
        )
        return non_semiconductor

    def _discount_score(self, relative_gap: Decimal) -> Decimal:
        normalized = (
            max(relative_gap, Decimal(0))
            / self._phase4_rules.excessive_discount_full_score_gap
            * Decimal(100)
        )
        return quantize_score(min(normalized, Decimal(100)))

    def close(self) -> None:
        dispose_db_engine(self._engine)
