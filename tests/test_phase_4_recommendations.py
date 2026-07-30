from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db.models.analysis import Recommendation
from app.db.models.market import PriceDaily, Stock
from app.db.models.portfolio import (
    PortfolioAllocation,
    RecommendationReason,
    RecommendationRun,
    SplitBuyPlan,
)
from app.db.session import create_db_engine, create_session_factory
from app.models.market_analysis import (
    MarketRegime,
    MetricEvidence,
    Phase3AnalysisResult,
    ProxyKind,
    ShockClassification,
    SourceKind,
)
from app.models.metadata import DataState, DataTiming
from app.models.recommendation import (
    MarketRecommendationContext,
    RecommendationCategory,
    RecommendationInput,
    RecommendationRunResult,
    SplitBuyStatus,
)
from app.models.scoring import (
    ComponentState,
    FilterResult,
    FilterState,
    IndustryComparison,
    Phase2Result,
    ScoreComponent,
)
from app.repositories.recommendation_repository import (
    RecommendationRepository,
)
from app.services.portfolio_service import (
    allocate_portfolio,
    attach_split_buy_plans,
    default_portfolio_profile,
    phase4_rules_from_settings,
)
from app.services.recommendation_rules import evaluate_recommendation
from app.services.recommendation_service import RecommendationService
from app.utils.dates import SEOUL
from tests.helpers import migrate_database

AS_OF = datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL)


def _phase2(
    *,
    investment_score: Decimal = Decimal(82),
    individual_entry_score: Decimal = Decimal(80),
    confidence: Decimal = Decimal(90),
    filter_state: FilterState = FilterState.PASS,
    discount: Decimal | None = None,
) -> Phase2Result:
    components = [
        ScoreComponent(
            score_name="INVESTMENT",
            code="DIVIDEND_CONTINUITY",
            state=ComponentState.AVAILABLE,
            raw_value=Decimal(1),
            normalized_value=Decimal(100),
            weight=Decimal(10),
            contribution=Decimal(10),
            explanation="최근 5개 사업연도 확정 DPS가 이어졌습니다.",
        )
    ]
    if discount is not None:
        components.append(
            ScoreComponent(
                score_name="INVESTMENT",
                code="MARKET_SHOCK_DISCOUNT",
                state=ComponentState.AVAILABLE,
                raw_value=discount,
                normalized_value=discount,
                weight=Decimal(15),
                contribution=discount * Decimal("0.15"),
                explanation="종목별 시장충격 할인 근거가 저장됐습니다.",
            )
        )
    return Phase2Result(
        symbol="000001",
        as_of_at=AS_OF,
        score_version="phase2-score-v1",
        rule_version="phase2-rule-v2",
        input_data_hash="1" * 64,
        filters=(
            FilterResult(
                code="AUDIT",
                name="감사의견",
                state=filter_state,
                reason=(
                    "최신 감사의견 적정"
                    if filter_state == FilterState.PASS
                    else "최신 감사의견이 투자배제 의견입니다."
                ),
            ),
        ),
        components=tuple(components),
        valuation_comparisons=(
            IndustryComparison(
                metric_code="PER",
                state=ComponentState.AVAILABLE,
                current_value=Decimal(8),
                industry_median=Decimal(10),
                industry_percentile=Decimal(30),
                comparison_level="DETAILED",
                classification_code="IND-A",
                sample_size=12,
                explanation="공식 세부 산업 양수 PER 표본을 사용했습니다.",
            ),
        ),
        investment_score=investment_score,
        individual_entry_score=individual_entry_score,
        data_confidence=confidence,
        recommendation_computable=filter_state == FilterState.PASS,
        explanation="Phase 2 검증 스냅샷",
        data_state=DataState.AVAILABLE,
    )


def _market(
    *,
    regime: MarketRegime = MarketRegime.GREEN,
    confidence: Decimal = Decimal(95),
    semiconductor_recovery: bool = True,
    breadth: bool = True,
) -> MarketRecommendationContext:
    return MarketRecommendationContext(
        snapshot_id=1,
        as_of_at=AS_OF,
        rule_version="phase3-rule-v2",
        input_data_hash="2" * 64,
        state=DataState.AVAILABLE,
        shock_classification=ShockClassification.MIXED,
        market_regime=regime,
        data_confidence=confidence,
        semiconductor_recovery=semiconductor_recovery,
        kospi_recovery=True,
        non_semiconductor_breadth=breadth,
        dividend_relative_strength_recovery=True,
    )


def _input(
    phase2: Phase2Result,
    market: MarketRecommendationContext,
) -> RecommendationInput:
    return RecommendationInput(
        stock_id=1,
        symbol="000001",
        name="검증종목",
        phase2_snapshot_id=1,
        phase2=phase2,
        market=market,
        is_semiconductor=False,
        reference_price=Decimal(50000),
        reference_price_date=AS_OF.date(),
        reference_price_provider="KIS",
        reference_price_currency="KRW",
    )


def test_forced_filter_failure_is_never_offset_by_high_score() -> None:
    rules = phase4_rules_from_settings(get_settings())
    decision = evaluate_recommendation(
        _input(
            _phase2(
                investment_score=Decimal(99),
                filter_state=FilterState.FAIL,
            ),
            _market(),
        ),
        rules,
    )

    assert decision.category == RecommendationCategory.EXCLUDED
    assert decision.exclusion_reasons == (
        "최신 감사의견이 투자배제 의견입니다.",
    )
    assert decision.target_weight is None


def test_low_confidence_is_data_insufficient_not_low_score() -> None:
    rules = phase4_rules_from_settings(get_settings())
    decision = evaluate_recommendation(
        _input(
            _phase2(confidence=Decimal(69)),
            _market(confidence=Decimal(95)),
        ),
        rules,
    )

    assert decision.category == RecommendationCategory.INSUFFICIENT_DATA
    assert decision.investment_score == Decimal(82)
    assert any("추천 기준" in reason for reason in decision.risk_reasons)


def test_excessive_discount_is_review_only_and_never_immediately_eligible() -> None:
    settings = get_settings()
    rules = phase4_rules_from_settings(settings)
    source = _input(
        _phase2(
            individual_entry_score=Decimal(30),
        ),
        _market(
            regime=MarketRegime.ORANGE,
            semiconductor_recovery=False,
            breadth=False,
        ),
    ).model_copy(
        update={
            "market_relative_return_gap": Decimal("0.09"),
            "market_shock_discount_score": Decimal(90),
        }
    )
    decision = evaluate_recommendation(source, rules)
    planned = attach_split_buy_plans((decision,), {1: source}, rules)[0]

    assert decision.category == RecommendationCategory.EXCESSIVE_DISCOUNT
    assert planned.split_buy_plan is not None
    assert (
        planned.split_buy_plan.status
        == SplitBuyStatus.HIDDEN_RISK_REVIEW
    )
    assert not any(
        tranche.eligible_now
        for tranche in planned.split_buy_plan.tranches
    )
    assert planned.split_buy_plan.is_order_executable is False


def test_portfolio_caps_and_split_buy_plan_are_deterministic() -> None:
    settings = get_settings()
    rules = phase4_rules_from_settings(settings)
    profile = default_portfolio_profile(settings).model_copy(
        update={"total_capital": Decimal(1000000)}
    )
    source = _input(_phase2(), _market())
    decision = evaluate_recommendation(source, rules)

    first = allocate_portfolio(
        (decision,),
        profile,
        MarketRegime.GREEN,
        rules,
    )
    second = allocate_portfolio(
        (decision,),
        profile,
        MarketRegime.GREEN,
        rules,
    )
    assert first == second
    assert first[0].target_weight is not None
    assert first[0].target_weight == profile.max_dividend_stock_weight
    assert first[0].target_weight <= profile.max_industry_weight

    planned = attach_split_buy_plans(first, {1: source}, rules)[0]
    assert planned.split_buy_plan is not None
    assert sum(
        (
            tranche.fraction_of_target
            for tranche in planned.split_buy_plan.tranches
        ),
        start=Decimal(0),
    ) == Decimal(1)
    assert all(
        tranche.target_price is None
        for tranche in planned.split_buy_plan.tranches
    )
    assert planned.split_buy_plan.reference_price == Decimal(50000)


def test_portfolio_weight_rounding_never_exceeds_stock_cap() -> None:
    settings = get_settings()
    rules = phase4_rules_from_settings(settings)
    stock_cap = Decimal("0.333333335")
    profile = default_portfolio_profile(settings).model_copy(
        update={
            "max_dividend_stock_weight": stock_cap,
            "max_industry_weight": Decimal(1),
        }
    )
    decision = evaluate_recommendation(
        _input(_phase2(), _market()),
        rules,
    )

    allocated = allocate_portfolio(
        (decision,),
        profile,
        MarketRegime.GREEN,
        rules,
    )[0]

    assert allocated.target_weight is not None
    assert allocated.target_weight <= stock_cap


def test_target_count_keeps_nonzero_growth_sleeve_from_being_starved() -> None:
    settings = get_settings()
    rules = phase4_rules_from_settings(settings)
    profile = default_portfolio_profile(settings).model_copy(
        update={"target_stock_count": 2}
    )
    sources = (
        _input(_phase2(), _market()),
        _input(_phase2(), _market()).model_copy(
            update={"stock_id": 2, "symbol": "000002", "name": "배당주2"}
        ),
        _input(_phase2(), _market()).model_copy(
            update={
                "stock_id": 3,
                "symbol": "000003",
                "name": "성장주",
                "is_semiconductor": True,
            }
        ),
    )
    decisions = tuple(evaluate_recommendation(item, rules) for item in sources)

    allocated = allocate_portfolio(
        decisions,
        profile,
        MarketRegime.GREEN,
        rules,
    )

    assert len(
        [
            item
            for item in allocated
            if item.target_weight is not None and item.target_weight > 0
        ]
    ) <= profile.target_stock_count
    assert any(
        item.sleeve.value == "GROWTH"
        and item.target_weight is not None
        and item.target_weight > 0
        for item in allocated
    )


def test_discount_benchmark_is_not_replaced_with_kospi_return() -> None:
    result = Phase3AnalysisResult(
        state=DataState.AVAILABLE,
        as_of_at=AS_OF,
        rule_version="phase3-rule-v2",
        input_data_hash="2" * 64,
        shock_classification=ShockClassification.MIXED,
        market_regime=MarketRegime.GREEN,
        data_confidence=Decimal(95),
        proxy_kind=ProxyKind.SELF_CALCULATED_PROXY,
        semiconductor_recovery=True,
        kospi_recovery=True,
        non_semiconductor_breadth=True,
        dividend_relative_strength_recovery=True,
        missing_core_data=(),
        explanation="검증용 Phase 3 결과",
        metrics=(
            MetricEvidence(
                code="KOSPI_RETURN",
                label="KOSPI 기간수익률",
                state=DataState.AVAILABLE,
                value=Decimal("-0.03"),
                source_provider="KRX",
                source_function="KOSPI 시리즈 일별시세정보",
                as_of_at=AS_OF,
                collected_at=AS_OF,
                calculation_method="기간 종가 수익률",
                data_quality="VERIFIED",
                data_timing=DataTiming.PREVIOUS_CLOSE,
                source_kind=SourceKind.OFFICIAL_API,
            ),
        ),
        contributions=(),
    )

    assert RecommendationService._market_reference_return(result) is None


def test_empty_universe_run_is_reused_without_fake_recommendations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "phase4-empty.db", monkeypatch)
    settings = get_settings().model_copy(update={"database_url": database_url})
    service = RecommendationService(settings)
    try:
        first = service.run_universe(as_of_at=AS_OF)
        second = service.run_universe(as_of_at=AS_OF)
    finally:
        service.close()

    assert first.run_id == second.run_id
    assert first.state == DataState.MISSING
    assert first.total_count == 0
    assert first.recommendations == ()
    assert "ACTIVE_KOSPI_UNIVERSE" in first.missing_core_data

    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions() as session:
        assert session.scalar(select(func.count(RecommendationRun.id))) == 1
        assert session.scalar(select(func.count(Recommendation.id))) == 0
    engine.dispose()


def test_repository_saves_reasons_plan_and_read_only_allocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "phase4-save.db", monkeypatch)
    settings = get_settings().model_copy(update={"database_url": database_url})
    rules = phase4_rules_from_settings(settings)
    profile = default_portfolio_profile(settings).model_copy(
        update={"total_capital": Decimal(1000000)}
    )
    source = _input(_phase2(), _market())
    decision = evaluate_recommendation(source, rules)
    decision = allocate_portfolio(
        (decision,),
        profile,
        MarketRegime.GREEN,
        rules,
    )[0]
    decision = attach_split_buy_plans(
        (decision,),
        {1: source},
        rules,
    )[0]

    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    repository = RecommendationRepository()
    with sessions.begin() as session:
        session.add(
            Stock(
                id=1,
                symbol="000001",
                name_ko="검증종목",
                is_kospi=True,
                is_active=True,
                source_provider="KRX",
                source_function="stored test snapshot",
                data_state=DataState.AVAILABLE.value,
                as_of_at=AS_OF,
                collected_at=AS_OF,
            )
        )
        session.flush()
        session.add(
            PriceDaily(
                stock_id=1,
                trade_date=AS_OF.date(),
                currency="KRW",
                close_price=Decimal(50000),
                is_adjusted=True,
                adjustment_status="VERIFIED",
                source_provider="KIS",
                source_function="verified adjusted daily price",
                data_state=DataState.AVAILABLE.value,
                as_of_at=AS_OF,
                collected_at=AS_OF,
                data_timing=DataTiming.PREVIOUS_CLOSE.value,
            )
        )
        profile_row = repository.save_profile(
            session,
            profile,
            source="TEST",
        )
        run_result = RecommendationRunResult(
            state=DataState.AVAILABLE,
            analyzed_at=AS_OF,
            as_of_at=AS_OF,
            basis_date=AS_OF.date(),
            score_version=rules.score_version,
            rule_version=rules.rule_version,
            market_rule_version="phase3-rule-v2",
            config_hash="3" * 64,
            input_data_hash="4" * 64,
            total_count=1,
            processed_count=1,
            recommended_count=1,
            excluded_count=0,
            insufficient_count=0,
            market_regime=MarketRegime.GREEN,
            recommendations=(decision,),
        )
        run = repository.save_run(
            session,
            run_result,
            portfolio_setting_id=profile_row.id,
            market_snapshot_id=None,
            source_snapshot_hashes={"market": "2" * 64},
            explanation="재현성 저장 테스트",
        )
        loaded = repository.load_run(session, run.id)
        assert loaded is not None
        assert loaded.recommendations[0].category == (
            RecommendationCategory.READY_FOR_RECOVERY
        )

    with sessions() as session:
        assert session.scalar(select(func.count(Recommendation.id))) == 1
        reason_count = session.scalar(
            select(func.count(RecommendationReason.id))
        )
        assert reason_count is not None
        assert reason_count >= 2
        plan = session.scalar(select(SplitBuyPlan))
        assert plan is not None
        assert plan.is_order_executable is False
        assert len(plan.tranches) == 4
        assert session.scalar(select(func.count(PortfolioAllocation.id))) == 1
    engine.dispose()

    service = RecommendationService(settings)
    try:
        assert service.save_position(
            symbol="000001",
            quantity=Decimal(30),
            average_purchase_price=Decimal(40000),
            as_of_at=AS_OF,
        )
        positions = service.positions()
    finally:
        service.close()
    assert len(positions) == 1
    assert positions[0]["holding_action"] == "REDUCE_REVIEW"
    assert positions[0]["current_weight"] == Decimal("1.5")

    service = RecommendationService(settings)
    try:
        assert service.save_position(
            symbol="000001",
            quantity=Decimal(30),
            average_purchase_price=Decimal(40000),
            currency="USD",
            as_of_at=AS_OF,
        )
        currency_mismatch = service.positions()
    finally:
        service.close()
    assert currency_mismatch[0]["current_weight"] is None
    assert currency_mismatch[0]["holding_action"] == "NOT_COMPUTABLE"


def test_same_snapshot_can_be_saved_under_different_portfolio_configs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "phase4-configs.db", monkeypatch)
    settings = get_settings().model_copy(update={"database_url": database_url})
    rules = phase4_rules_from_settings(settings)
    first_profile = default_portfolio_profile(settings)
    second_profile = first_profile.model_copy(
        update={"target_stock_count": first_profile.target_stock_count + 1}
    )
    source = _input(_phase2(), _market())
    decision = evaluate_recommendation(source, rules)
    decision = attach_split_buy_plans(
        (decision,),
        {source.stock_id: source},
        rules,
    )[0]

    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    repository = RecommendationRepository()
    with sessions.begin() as session:
        session.add(
            Stock(
                id=source.stock_id,
                symbol=source.symbol,
                name_ko=source.name,
                is_kospi=True,
                is_active=True,
                source_provider="KRX",
                source_function="stored test snapshot",
                data_state=DataState.AVAILABLE.value,
                as_of_at=AS_OF,
                collected_at=AS_OF,
            )
        )
        session.flush()
        first_profile_row = repository.save_profile(
            session,
            first_profile,
            source="TEST",
        )
        second_profile_row = repository.save_profile(
            session,
            second_profile,
            source="TEST",
        )
        for config_hash, profile_id in (
            ("3" * 64, first_profile_row.id),
            ("5" * 64, second_profile_row.id),
        ):
            result = RecommendationRunResult(
                state=DataState.AVAILABLE,
                analyzed_at=AS_OF,
                as_of_at=AS_OF,
                basis_date=AS_OF.date(),
                score_version=rules.score_version,
                rule_version=rules.rule_version,
                market_rule_version="phase3-rule-v2",
                config_hash=config_hash,
                input_data_hash="4" * 64,
                total_count=1,
                processed_count=1,
                recommended_count=1,
                excluded_count=0,
                insufficient_count=0,
                market_regime=MarketRegime.GREEN,
                recommendations=(decision,),
            )
            repository.save_run(
                session,
                result,
                portfolio_setting_id=profile_id,
                market_snapshot_id=None,
                source_snapshot_hashes={"market": "2" * 64},
                explanation="설정별 재현성 저장 테스트",
            )

    with sessions() as session:
        assert session.scalar(select(func.count(RecommendationRun.id))) == 2
        assert session.scalar(select(func.count(Recommendation.id))) == 2
    engine.dispose()


def test_reference_price_provenance_is_part_of_snapshot_identity() -> None:
    first = _input(_phase2(), _market())
    second = first.model_copy(update={"reference_price_currency": "USD"})

    assert RecommendationService._phase2_source_snapshot(
        first
    ) != RecommendationService._phase2_source_snapshot(second)


def test_all_insufficient_results_make_run_state_missing() -> None:
    state, missing = RecommendationService._run_state(
        total=2,
        insufficient_count=2,
        market_state=DataState.AVAILABLE,
        market_missing=(),
    )

    assert state == DataState.MISSING
    assert "ALL_STOCKS_INSUFFICIENT_DATA" in missing


def test_semantically_identical_profile_mapping_reuses_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "profile-hash.db", monkeypatch)
    settings = get_settings().model_copy(update={"database_url": database_url})
    profile = default_portfolio_profile(settings)
    reordered = profile.model_copy(
        update={"regime_targets": dict(reversed(profile.regime_targets.items()))}
    )
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    repository = RecommendationRepository()

    with sessions.begin() as session:
        first = repository.save_profile(session, profile, source="TEST")
        first_id = first.id
    with sessions.begin() as session:
        second = repository.save_profile(session, reordered, source="TEST")
        second_id = second.id

    assert first_id == second_id
    engine.dispose()


def test_resaving_old_profile_makes_it_latest_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(
        tmp_path / "profile-selection.db",
        monkeypatch,
    )
    settings = get_settings().model_copy(update={"database_url": database_url})
    first_profile = default_portfolio_profile(settings)
    second_profile = first_profile.model_copy(
        update={"profile_name": "두 번째 설정"}
    )
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    repository = RecommendationRepository()

    with sessions.begin() as session:
        first = repository.save_profile(session, first_profile, source="TEST")
        first_id = first.id
    with sessions.begin() as session:
        repository.save_profile(session, second_profile, source="TEST")
    with sessions.begin() as session:
        repository.save_profile(session, first_profile, source="TEST")
    with sessions() as session:
        latest = repository.latest_profile(session)

    assert latest is not None
    assert latest[0] == first_id
    engine.dispose()
