from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.db.models.analysis import (
    ForcedFilterResult,
    ScoreComponentRecord,
    ScoreSnapshot,
    ValuationComparisonRecord,
)
from app.db.models.financial import (
    AuditOpinion,
    Dividend,
    FinancialAccount,
    FinancialStatement,
)
from app.db.models.market import (
    MarketStatus,
    PriceDaily,
    Stock,
    StockClassification,
)
from app.db.session import create_db_engine, create_session_factory
from app.models.metadata import DataState, FinancialScope
from app.models.scoring import (
    AuditFilterEvidence,
    ComponentState,
    CorporateEventEvidence,
    DataConfidenceEvidence,
    DividendPayment,
    DividendQualityEvidence,
    EntityKind,
    EntryEvidence,
    FilterState,
    FinancialQualityEvidence,
    FinancialRiskEvidence,
    IndustryPeer,
    LiquidityEvidence,
    MarketFilterEvidence,
    Phase2Evidence,
    Phase2Rules,
    ValuationEvidence,
)
from app.repositories.financial_repository import FinancialRepository
from app.repositories.phase2_input_repository import Phase2InputRepository
from app.repositories.scoring_repository import ScoringRepository
from app.services.forced_filter_service import evaluate_forced_filters
from app.services.phase2_input_service import (
    Phase2InputAssembler,
    _effective_industry_sample_size,
)
from app.services.phase2_service import Phase2ScoringService
from app.services.scoring_rules import phase2_rules_from_settings
from app.services.scoring_service import evaluate_phase2
from app.services.valuation_service import select_industry_comparison
from app.utils.dates import SEOUL
from tests.helpers import make_settings, migrate_database


def _peers(count: int, *, detailed: str | None) -> tuple[IndustryPeer, ...]:
    return tuple(
        IndustryPeer(
            symbol=f"{index:06d}",
            detailed_industry=detailed,
            parent_industry="PARENT",
            per=Decimal(10 + index) / Decimal(2),
            pbr=Decimal(8 + index) / Decimal(10),
            roe=Decimal("0.10"),
        )
        for index in range(1, count + 1)
    )


def _valid_evidence() -> Phase2Evidence:
    return Phase2Evidence(
        symbol="000001",
        as_of_at=datetime(2026, 7, 29, 15, 30, tzinfo=SEOUL),
        market=MarketFilterEvidence(
            is_kospi=True,
            product_type="STOCK",
            share_class="COMMON",
            listing_status="LISTED",
            official_status_coverage=True,
            trading_suspended=False,
            management_issue=False,
            delisting_risk=False,
        ),
        audit=AuditFilterEvidence(
            opinion="적정",
            filing_date=date(2026, 3, 31),
            going_concern_risk=False,
            going_concern_status="VERIFIED",
        ),
        liquidity=LiquidityEvidence(
            trading_values_60=tuple(Decimal(2000000000) for _ in range(60)),
            volumes_20=tuple(Decimal(1000) for _ in range(20)),
            currency="KRW",
            source_verified=True,
            planned_order_amount=Decimal(5000000),
        ),
        corporate_event=CorporateEventEvidence(
            coverage_verified=True,
            severe_event=False,
            manual_review_event=False,
        ),
        financial_risk=FinancialRiskEvidence(
            entity_kind=EntityKind.NON_FINANCIAL,
            operating_profit_ttm=Decimal(100),
            finance_costs_ttm=Decimal(20),
            repeated_operating_loss_years=0,
            currency="KRW",
        ),
        dividend=DividendQualityEvidence(
            payments=(
                DividendPayment(business_year=2021, dps=Decimal(100)),
                DividendPayment(business_year=2022, dps=Decimal(105)),
                DividendPayment(business_year=2023, dps=Decimal(110)),
                DividendPayment(business_year=2024, dps=Decimal(115)),
                DividendPayment(business_year=2025, dps=Decimal(120)),
            ),
            latest_total_dividend=Decimal(30),
            parent_net_income_ttm=Decimal(100),
            operating_cash_flow_ttm=Decimal(80),
            capex_tangible_ttm=Decimal(10),
            capex_intangible_ttm=Decimal(5),
            currency="KRW",
        ),
        financial_quality=FinancialQualityEvidence(
            revenue_ttm=Decimal(1000),
            operating_profit_ttm=Decimal(100),
            parent_net_income_ttm=Decimal(100),
            assets=Decimal(1000),
            liabilities=Decimal(500),
            parent_equity=Decimal(500),
            operating_cash_flow_ttm=Decimal(80),
            currency="KRW",
        ),
        valuation=ValuationEvidence(
            current_per=Decimal(8),
            current_pbr=Decimal("0.8"),
            detailed_industry="DETAIL",
            parent_industry="PARENT",
            peers=_peers(12, detailed="DETAIL"),
            historical_per=(
                Decimal(9),
                Decimal(10),
                Decimal(11),
                Decimal(12),
                Decimal(13),
            ),
            historical_pbr=(
                Decimal("0.9"),
                Decimal("1.0"),
                Decimal("1.1"),
                Decimal("1.2"),
                Decimal("1.3"),
            ),
            entity_kind=EntityKind.NON_FINANCIAL,
        ),
        confidence=DataConfidenceEvidence(
            required_items_present=10,
            required_items_total=10,
            max_age_days=30,
            official_source_ratio=Decimal(1),
            cross_validation_verified=True,
            industry_sample_size=12,
            adjusted_price_verified=True,
            account_mapping_ratio=Decimal(1),
        ),
        entry=EntryEvidence(
            adjusted_price_verified=True,
            close=Decimal(110),
            rsi_14=Decimal(50),
            sma_20=Decimal(105),
            sma_60=Decimal(100),
        ),
    )


def test_forced_filter_failure_cannot_be_offset_by_high_scores() -> None:
    evidence = _valid_evidence()
    evidence = evidence.model_copy(
        update={
            "market": evidence.market.model_copy(
                update={"trading_suspended": True}
            )
        }
    )

    result = evaluate_phase2(evidence, Phase2Rules())

    assert any(
        item.code == "MARKET_STATUS" and item.state == FilterState.FAIL
        for item in result.filters
    )
    assert result.investment_score is None
    assert result.recommendation_computable is False


def test_missing_core_data_is_not_converted_to_a_low_score() -> None:
    evidence = _valid_evidence().model_copy(update={"audit": None})

    result = evaluate_phase2(evidence, Phase2Rules())

    assert result.investment_score is None
    assert result.recommendation_computable is False
    assert "AUDIT_OPINION" in result.missing_core_data
    assert any(
        item.code == "AUDIT_OPINION"
        and item.state == FilterState.MISSING
        for item in result.filters
    )


def test_unknown_market_classification_is_missing_not_a_confirmed_failure() -> None:
    evidence = _valid_evidence()
    market = evidence.market.model_copy(update={"product_type": "UNKNOWN"})

    filters = evaluate_forced_filters(
        market,
        evidence.audit,
        evidence.liquidity,
        evidence.corporate_event,
        evidence.financial_risk,
        as_of_date=evidence.as_of_at.date(),
        rules=Phase2Rules(),
    )

    market_filter = next(
        item for item in filters if item.code == "MARKET_UNIVERSE"
    )
    assert market_filter.state == FilterState.MISSING


def test_spaced_disclaimer_audit_opinion_is_rejected() -> None:
    evidence = _valid_evidence()
    assert evidence.audit is not None
    audit = evidence.audit.model_copy(update={"opinion": "감사의견 거절"})

    filters = evaluate_forced_filters(
        evidence.market,
        audit,
        evidence.liquidity,
        evidence.corporate_event,
        evidence.financial_risk,
        as_of_date=evidence.as_of_at.date(),
        rules=Phase2Rules(),
    )

    audit_filter = next(
        item for item in filters if item.code == "AUDIT_OPINION"
    )
    assert audit_filter.state == FilterState.FAIL


def test_audit_older_than_twelve_months_is_not_accepted_as_current() -> None:
    evidence = _valid_evidence()
    assert evidence.audit is not None
    audit = evidence.audit.model_copy(
        update={"filing_date": evidence.as_of_at.date() - timedelta(days=366)}
    )

    filters = evaluate_forced_filters(
        evidence.market,
        audit,
        evidence.liquidity,
        evidence.corporate_event,
        evidence.financial_risk,
        as_of_date=evidence.as_of_at.date(),
        rules=Phase2Rules(),
    )

    audit_filter = next(
        item for item in filters if item.code == "AUDIT_OPINION"
    )
    assert audit_filter.state == FilterState.MISSING


def test_single_low_interest_coverage_period_requires_review_not_failure() -> None:
    evidence = _valid_evidence()
    financial_risk = FinancialRiskEvidence(
        entity_kind=EntityKind.NON_FINANCIAL,
        operating_profit_ttm=Decimal(50),
        finance_costs_ttm=Decimal(100),
        repeated_operating_loss_years=0,
        currency="KRW",
    )

    filters = evaluate_forced_filters(
        evidence.market,
        evidence.audit,
        evidence.liquidity,
        evidence.corporate_event,
        financial_risk,
        as_of_date=evidence.as_of_at.date(),
        rules=Phase2Rules(),
    )

    financial_filter = next(
        item for item in filters if item.code == "FINANCIAL_RISK"
    )
    assert financial_filter.state == FilterState.REVIEW_REQUIRED
    assert "지속" in financial_filter.reason


def test_financial_model_availability_alone_never_means_filter_passed() -> None:
    evidence = _valid_evidence()
    financial_risk = FinancialRiskEvidence(
        entity_kind=EntityKind.FINANCIAL,
        financial_model_available=True,
    )

    filters = evaluate_forced_filters(
        evidence.market,
        evidence.audit,
        evidence.liquidity,
        evidence.corporate_event,
        financial_risk,
        as_of_date=evidence.as_of_at.date(),
        rules=Phase2Rules(),
    )

    financial_filter = next(
        item for item in filters if item.code == "FINANCIAL_RISK"
    )
    assert financial_filter.state == FilterState.MISSING


def test_financial_company_never_uses_general_interest_coverage() -> None:
    evidence = _valid_evidence()
    financial_risk = FinancialRiskEvidence(
        entity_kind=EntityKind.FINANCIAL,
        operating_profit_ttm=Decimal(-100),
        finance_costs_ttm=Decimal(1),
        repeated_operating_loss_years=3,
        currency="KRW",
        financial_model_available=False,
    )

    filters = evaluate_forced_filters(
        evidence.market,
        evidence.audit,
        evidence.liquidity,
        evidence.corporate_event,
        financial_risk,
        as_of_date=evidence.as_of_at.date(),
        rules=Phase2Rules(),
    )

    financial_filter = next(
        item for item in filters if item.code == "FINANCIAL_RISK"
    )
    assert financial_filter.state == FilterState.MISSING
    assert financial_filter.raw_value is None
    assert "별도 평가모형" in financial_filter.reason


def test_liquidity_uses_median_and_planned_order_ratio() -> None:
    evidence = _valid_evidence()
    trading_values = (
        *(Decimal(2000000000) for _ in range(59)),
        Decimal(999999999999),
    )
    assert evidence.liquidity is not None
    liquidity = evidence.liquidity.model_copy(
        update={"trading_values_60": trading_values}
    )
    filters = evaluate_forced_filters(
        evidence.market,
        evidence.audit,
        liquidity,
        evidence.corporate_event,
        evidence.financial_risk,
        as_of_date=evidence.as_of_at.date(),
        rules=Phase2Rules(),
    )
    liquidity_filter = next(
        item for item in filters if item.code == "LIQUIDITY"
    )
    assert liquidity_filter.state == FilterState.PASS
    assert liquidity_filter.raw_value == Decimal(2000000000)

    failed = liquidity.model_copy(
        update={"planned_order_amount": Decimal(10000001)}
    )
    failed_filters = evaluate_forced_filters(
        evidence.market,
        evidence.audit,
        failed,
        evidence.corporate_event,
        evidence.financial_risk,
        as_of_date=evidence.as_of_at.date(),
        rules=Phase2Rules(),
    )
    failed_liquidity = next(
        item for item in failed_filters if item.code == "LIQUIDITY"
    )
    assert failed_liquidity.state == FilterState.FAIL


def test_liquidity_order_ratio_uses_recent_20_day_median() -> None:
    evidence = _valid_evidence()
    assert evidence.liquidity is not None
    liquidity = evidence.liquidity.model_copy(
        update={
            "trading_values_60": (
                *(Decimal(100000000000) for _ in range(40)),
                *(Decimal(1000000000) for _ in range(20)),
            ),
            "planned_order_amount": Decimal(6000000),
        }
    )

    filters = evaluate_forced_filters(
        evidence.market,
        evidence.audit,
        liquidity,
        evidence.corporate_event,
        evidence.financial_risk,
        as_of_date=evidence.as_of_at.date(),
        rules=Phase2Rules(),
    )

    liquidity_filter = next(
        item for item in filters if item.code == "LIQUIDITY"
    )
    assert liquidity_filter.state == FilterState.FAIL
    assert "order_median_20=1000000000" in (liquidity_filter.raw_text or "")


def test_negative_per_never_receives_an_undervaluation_score() -> None:
    evidence = _valid_evidence()
    assert evidence.valuation is not None
    evidence = evidence.model_copy(
        update={
            "valuation": evidence.valuation.model_copy(
                update={"current_per": Decimal(-5)}
            )
        }
    )

    result = evaluate_phase2(evidence, Phase2Rules())
    per_components = [
        item
        for item in result.components
        if item.code in {"INDUSTRY_PER", "HISTORICAL_PER"}
    ]

    assert per_components
    assert all(
        item.state == ComponentState.NOT_APPLICABLE
        and item.normalized_value is None
        and item.contribution is None
        for item in per_components
    )
    assert result.investment_score is None


def test_small_detailed_industry_falls_back_to_parent() -> None:
    detailed = _peers(4, detailed="DETAIL")
    parent_only = tuple(
        peer.model_copy(update={"detailed_industry": "OTHER"})
        for peer in _peers(10, detailed="DETAIL")
    )
    valid_evidence = _valid_evidence()
    assert valid_evidence.valuation is not None
    evidence = valid_evidence.valuation.model_copy(
        update={"peers": detailed + parent_only}
    )

    comparison = select_industry_comparison(
        evidence,
        metric_code="PER",
        minimum_sample=10,
    )

    assert comparison.state == ComponentState.AVAILABLE
    assert comparison.comparison_level == "PARENT"
    assert comparison.sample_size == 14


def test_confidence_industry_sample_counts_only_usable_per_and_pbr() -> None:
    peers = tuple(
        peer.model_copy(update={"per": None})
        for peer in _peers(12, detailed="DETAIL")
    )

    sample_size = _effective_industry_sample_size(
        peers,
        detailed_industry="DETAIL",
        parent_industry="PARENT",
        minimum_sample=10,
    )

    assert sample_size == 0


def test_explainable_phase2_score_preserves_all_component_inputs() -> None:
    result = evaluate_phase2(_valid_evidence(), Phase2Rules())

    assert all(item.state == FilterState.PASS for item in result.filters)
    assert result.investment_score is not None
    assert result.entry_score is None
    assert result.individual_entry_score is not None
    assert result.data_confidence is not None
    assert result.recommendation_computable is True
    assert result.score_scope == "PHASE2_CORE_ONLY"
    assert result.components
    for component in result.components:
        if component.state == ComponentState.AVAILABLE:
            assert component.raw_value is not None
            assert component.normalized_value is not None
            assert component.weight is not None
            assert component.contribution is not None
            assert component.explanation


def test_low_confidence_stops_recommendation_without_erasing_score() -> None:
    evidence = _valid_evidence()
    evidence = evidence.model_copy(
        update={
            "confidence": evidence.confidence.model_copy(
                update={
                    "required_items_present": 7,
                    "official_source_ratio": Decimal("0.5"),
                    "cross_validation_verified": False,
                    "adjusted_price_verified": False,
                }
            )
        }
    )

    result = evaluate_phase2(evidence, Phase2Rules())

    assert result.investment_score is not None
    assert result.data_confidence is not None
    assert result.data_confidence < Decimal(70)
    assert result.recommendation_computable is False
    assert "데이터 신뢰도" in result.explanation


def test_identical_inputs_and_rules_produce_identical_hash_and_result() -> None:
    evidence = _valid_evidence()
    rules = Phase2Rules()

    first = evaluate_phase2(evidence, rules)
    second = evaluate_phase2(evidence, rules)

    assert first.input_data_hash == second.input_data_hash
    assert first == second


def test_phase2_rules_are_loaded_from_config() -> None:
    settings = make_settings(
        phase2_score_version="score-test",
        phase2_rule_version="rule-test",
        phase2_order_median_days=15,
        phase2_minimum_median_trading_value=Decimal(123),
        phase2_industry_minimum_sample=12,
    )

    rules = phase2_rules_from_settings(settings)

    assert rules.score_version == "score-test"
    assert rules.rule_version == "rule-test"
    assert rules.order_median_days == 15
    assert rules.minimum_median_trading_value == Decimal(123)
    assert rules.industry_minimum_sample == 12


def test_default_rule_version_changes_when_filter_semantics_change() -> None:
    assert Phase2Rules().rule_version == "phase2-rule-v2"
    assert phase2_rules_from_settings(
        make_settings()
    ).rule_version == "phase2-rule-v2"


def test_unrecognized_market_status_values_do_not_create_safe_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(
        tmp_path / "phase2-status-vocabulary.db",
        monkeypatch,
    )
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    as_of_at = datetime(2026, 7, 29, 15, 30, tzinfo=SEOUL)

    with sessions.begin() as session:
        stock = Stock(
            symbol="000008",
            name_ko="상태값검증",
            is_kospi=True,
            security_type="STOCK",
            share_class="COMMON",
            listing_status="LISTED",
            is_active=True,
            source_provider="KRX",
            source_function="test fixture",
            data_state="AVAILABLE",
            as_of_at=as_of_at,
            collected_at=as_of_at,
        )
        session.add(stock)
        session.flush()
        for status_type in (
            "TRADING_STATUS",
            "MANAGEMENT_STATUS",
            "DELISTING_RISK",
        ):
            session.add(
                MarketStatus(
                    stock_id=stock.id,
                    status_type=status_type,
                    status_value="UNKNOWN",
                    effective_from=as_of_at - timedelta(days=1),
                    source_provider="KRX",
                    source_function="test fixture",
                    data_state="AVAILABLE",
                    as_of_at=as_of_at,
                    collected_at=as_of_at,
                )
            )

    with sessions() as session:
        stock = session.query(Stock).filter_by(symbol="000008").one()
        evidence = Phase2InputAssembler().assemble(
            session,
            stock,
            as_of_at=as_of_at,
            rules=Phase2Rules(),
            planned_order_amount=Decimal(1000000),
        )

    engine.dispose()
    assert evidence.market.official_status_coverage is False
    assert evidence.market.trading_suspended is None
    assert evidence.market.management_issue is None
    assert evidence.market.delisting_risk is None


def test_input_assembler_excludes_records_collected_after_as_of(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "phase2-as-of.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    as_of_at = datetime(2025, 12, 31, 15, 30, tzinfo=SEOUL)
    future_collected_at = datetime(2026, 1, 2, 9, 0, tzinfo=SEOUL)

    with sessions.begin() as session:
        stock = Stock(
            symbol="000002",
            name_ko="시점검증종목",
            is_kospi=True,
            security_type="STOCK",
            share_class="COMMON",
            listing_status="LISTED",
            is_active=True,
            source_provider="KRX",
            source_function="test fixture",
            data_state="AVAILABLE",
            as_of_at=as_of_at,
            collected_at=as_of_at,
        )
        session.add(stock)
        session.flush()
        session.add_all(
            (
                StockClassification(
                    stock_id=stock.id,
                    classification_system="KRX_INDUSTRY_KIND",
                    classification_code="FINANCIAL",
                    valid_from=date(2020, 1, 1),
                    source_provider="KRX",
                    source_function="test fixture",
                    data_state="AVAILABLE",
                    as_of_at=as_of_at,
                    collected_at=future_collected_at,
                ),
                MarketStatus(
                    stock_id=stock.id,
                    status_type="CORPORATE_EVENT_SCREEN",
                    status_value="CLEAR",
                    effective_from=as_of_at,
                    source_provider="OpenDART",
                    source_function="test fixture",
                    data_state="AVAILABLE",
                    as_of_at=as_of_at,
                    collected_at=future_collected_at,
                ),
            )
        )

    with sessions() as session:
        stock = session.query(Stock).filter_by(symbol="000002").one()
        evidence = Phase2InputAssembler().assemble(
            session,
            stock,
            as_of_at=as_of_at,
            rules=Phase2Rules(),
            planned_order_amount=Decimal(1000000),
        )

    engine.dispose()
    assert evidence.financial_risk is not None
    assert evidence.financial_risk.entity_kind == EntityKind.UNKNOWN
    assert evidence.corporate_event is not None
    assert evidence.corporate_event.coverage_verified is False


def test_input_assembler_does_not_use_future_stock_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(
        tmp_path / "phase2-stock-as-of.db",
        monkeypatch,
    )
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    as_of_at = datetime(2025, 12, 31, 15, 30, tzinfo=SEOUL)
    future_at = datetime(2026, 1, 2, 9, 0, tzinfo=SEOUL)

    with sessions.begin() as session:
        stock = Stock(
            symbol="000003",
            name_ko="미래스냅샷",
            is_kospi=True,
            security_type="STOCK",
            share_class="COMMON",
            listing_status="LISTED",
            is_active=True,
            source_provider="KRX",
            source_function="test fixture",
            data_state="AVAILABLE",
            as_of_at=future_at,
            collected_at=future_at,
        )
        session.add(stock)

    with sessions() as session:
        stock = session.query(Stock).filter_by(symbol="000003").one()
        evidence = Phase2InputAssembler().assemble(
            session,
            stock,
            as_of_at=as_of_at,
            rules=Phase2Rules(),
            planned_order_amount=Decimal(1000000),
        )

    engine.dispose()
    assert evidence.market.is_kospi is None
    assert evidence.market.product_type is None
    assert evidence.market.share_class is None
    assert evidence.market.listing_status is None


def test_zero_close_is_preserved_in_raw_data_but_not_used_as_entry_price(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(
        tmp_path / "phase2-zero-price.db",
        monkeypatch,
    )
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    as_of_at = datetime(2026, 7, 29, 15, 30, tzinfo=SEOUL)

    with sessions.begin() as session:
        stock = Stock(
            symbol="000004",
            name_ko="가격0검증",
            is_active=True,
            source_provider="KRX",
            source_function="test fixture",
            data_state="AVAILABLE",
            as_of_at=as_of_at,
            collected_at=as_of_at,
        )
        session.add(stock)
        session.flush()
        session.add(
            PriceDaily(
                stock_id=stock.id,
                trade_date=as_of_at.date(),
                currency="KRW",
                high_price=Decimal(0),
                low_price=Decimal(0),
                close_price=Decimal(0),
                volume=Decimal(0),
                trading_value=Decimal(0),
                is_adjusted=True,
                adjustment_status="VERIFIED",
                source_provider="KRX",
                source_function="test fixture",
                data_state="AVAILABLE",
                as_of_at=as_of_at,
                collected_at=as_of_at,
            )
        )

    with sessions() as session:
        stock = session.query(Stock).filter_by(symbol="000004").one()
        evidence = Phase2InputAssembler().assemble(
            session,
            stock,
            as_of_at=as_of_at,
            rules=Phase2Rules(),
            planned_order_amount=Decimal(1000000),
        )
        stored_close = session.query(PriceDaily.close_price).scalar()

    engine.dispose()
    assert stored_close == Decimal(0)
    assert evidence.entry is not None
    assert evidence.entry.close is None
    assert evidence.entry.adjusted_price_verified is True


def test_phase2_price_inputs_exclude_rows_collected_after_as_of(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(
        tmp_path / "phase2-price-collected-at.db",
        monkeypatch,
    )
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    as_of_at = datetime(2026, 7, 29, 15, 30, tzinfo=SEOUL)

    with sessions.begin() as session:
        stock = Stock(
            symbol="000009",
            name_ko="가격시점검증",
            is_active=True,
            source_provider="KRX",
            source_function="test fixture",
            data_state="AVAILABLE",
            as_of_at=as_of_at,
            collected_at=as_of_at,
        )
        session.add(stock)
        session.flush()
        session.add(
            PriceDaily(
                stock_id=stock.id,
                trade_date=as_of_at.date() - timedelta(days=1),
                currency="KRW",
                high_price=Decimal(101),
                low_price=Decimal(99),
                close_price=Decimal(100),
                volume=Decimal(1000),
                trading_value=Decimal(2000000000),
                market_cap=Decimal(100000000000),
                is_adjusted=True,
                adjustment_status="VERIFIED",
                source_provider="KIS",
                source_function="test fixture",
                data_state="AVAILABLE",
                as_of_at=as_of_at,
                collected_at=as_of_at + timedelta(days=1),
            )
        )
        stock_id = stock.id

    with sessions() as session:
        rows = Phase2InputRepository().price_rows(
            session,
            stock_id,
            as_of_at,
        )

    engine.dispose()
    assert rows == []


def test_entry_price_uses_same_verified_source_as_technical_indicators(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(
        tmp_path / "phase2-entry-source.db",
        monkeypatch,
    )
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    as_of_at = datetime(2026, 7, 29, 15, 30, tzinfo=SEOUL)
    first_date = as_of_at.date() - timedelta(days=200)

    with sessions.begin() as session:
        stock = Stock(
            symbol="000010",
            name_ko="진입가격원천검증",
            is_active=True,
            source_provider="KRX",
            source_function="test fixture",
            data_state="AVAILABLE",
            as_of_at=as_of_at,
            collected_at=as_of_at,
        )
        session.add(stock)
        session.flush()
        for index in range(200):
            close = Decimal(100 + index)
            session.add(
                PriceDaily(
                    stock_id=stock.id,
                    trade_date=first_date + timedelta(days=index),
                    currency="KRW",
                    high_price=close + Decimal(1),
                    low_price=close - Decimal(1),
                    close_price=close,
                    volume=Decimal(1000),
                    trading_value=Decimal(2000000000),
                    is_adjusted=True,
                    adjustment_status="VERIFIED",
                    source_provider="KIS",
                    source_function="test fixture",
                    data_state="AVAILABLE",
                    as_of_at=as_of_at,
                    collected_at=as_of_at,
                )
            )
        session.add(
            PriceDaily(
                stock_id=stock.id,
                trade_date=as_of_at.date(),
                currency="KRW",
                high_price=Decimal(1000),
                low_price=Decimal(998),
                close_price=Decimal(999),
                volume=Decimal(1000),
                trading_value=Decimal(2000000000),
                is_adjusted=False,
                adjustment_status="NOT_VERIFIED",
                source_provider="KRX",
                source_function="test fixture",
                data_state="AVAILABLE",
                as_of_at=as_of_at,
                collected_at=as_of_at,
            )
        )

    with sessions() as session:
        stock = session.query(Stock).filter_by(symbol="000010").one()
        evidence = Phase2InputAssembler().assemble(
            session,
            stock,
            as_of_at=as_of_at,
            rules=Phase2Rules(),
            planned_order_amount=Decimal(1000000),
        )

    engine.dispose()
    assert evidence.entry is not None
    assert evidence.entry.adjusted_price_verified is True
    assert evidence.entry.close == Decimal(299)


def test_financial_read_models_ignore_non_available_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(
        tmp_path / "phase2-financial-state.db",
        monkeypatch,
    )
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    collected_at = datetime(2026, 7, 29, 15, 30, tzinfo=SEOUL)

    with sessions.begin() as session:
        stock = Stock(
            symbol="000011",
            name_ko="재무상태검증",
            is_active=True,
            source_provider="KRX",
            source_function="test fixture",
            data_state="AVAILABLE",
            as_of_at=collected_at,
            collected_at=collected_at,
        )
        session.add(stock)
        session.flush()
        for year, state, receipt, amount in (
            (2024, "AVAILABLE", "20250331000001", Decimal(100)),
            (2025, "MISSING", "20260331000001", Decimal(999)),
        ):
            statement = FinancialStatement(
                stock_id=stock.id,
                corp_code="00126380",
                receipt_no=receipt,
                report_code="11011",
                business_year=year,
                statement_kind="IS",
                fs_div="CFS",
                filing_date=date(year + 1, 3, 31),
                source_provider="OpenDART",
                source_function="test fixture",
                data_state=state,
                collected_at=collected_at,
                data_timing="PERIODIC_DISCLOSURE",
            )
            session.add(statement)
            session.flush()
            session.add(
                FinancialAccount(
                    statement_id=statement.id,
                    account_id="ifrs-full_Revenue",
                    account_name="매출액",
                    statement_section="IS",
                    amount=amount,
                    current_amount=amount,
                    unit="KRW",
                    canonical_metric_code="REVENUE",
                    mapping_status="MAPPED",
                )
            )
        session.add_all(
            (
                Dividend(
                    stock_id=stock.id,
                    receipt_no="20250331000002",
                    business_year=2024,
                    stock_kind="보통주",
                    dps=Decimal(100),
                    currency="KRW",
                    filing_date=date(2025, 3, 31),
                    is_confirmed=True,
                    is_estimate=False,
                    source_provider="OpenDART",
                    source_function="test fixture",
                    data_state="AVAILABLE",
                    collected_at=collected_at,
                    data_timing="PERIODIC_DISCLOSURE",
                ),
                Dividend(
                    stock_id=stock.id,
                    receipt_no="20260331000002",
                    business_year=2025,
                    stock_kind="보통주",
                    dps=Decimal(999),
                    currency="KRW",
                    filing_date=date(2026, 3, 31),
                    is_confirmed=True,
                    is_estimate=False,
                    source_provider="OpenDART",
                    source_function="test fixture",
                    data_state="MISSING",
                    collected_at=collected_at,
                    data_timing="PERIODIC_DISCLOSURE",
                ),
                AuditOpinion(
                    stock_id=stock.id,
                    receipt_no="20250331000003",
                    business_year=2024,
                    opinion="적정",
                    filing_date=date(2025, 3, 31),
                    going_concern_status="VERIFIED",
                    going_concern_risk=False,
                    emphasis_status="AVAILABLE",
                    source_provider="OpenDART",
                    source_function="test fixture",
                    data_state="AVAILABLE",
                    collected_at=collected_at,
                    data_timing="PERIODIC_DISCLOSURE",
                ),
                AuditOpinion(
                    stock_id=stock.id,
                    receipt_no="20260331000003",
                    business_year=2025,
                    opinion="부적정",
                    filing_date=date(2026, 3, 31),
                    going_concern_status="VERIFIED",
                    going_concern_risk=True,
                    emphasis_status="AVAILABLE",
                    source_provider="OpenDART",
                    source_function="test fixture",
                    data_state="MISSING",
                    collected_at=collected_at,
                    data_timing="PERIODIC_DISCLOSURE",
                ),
            )
        )
        stock_id = stock.id

    repository = FinancialRepository()
    with sessions() as session:
        scope, accounts = repository.latest_mapped_accounts(
            session,
            stock_id,
            as_of_date=date(2026, 7, 29),
        )
        dividends = repository.dividend_history(
            session,
            stock_id,
            as_of_date=date(2026, 7, 29),
        )
        audit = repository.latest_audit(
            session,
            stock_id,
            as_of_date=date(2026, 7, 29),
        )

    engine.dispose()
    assert scope == FinancialScope.CONSOLIDATED
    assert len(accounts) == 1
    assert accounts[0].business_year == 2024
    assert accounts[0].value == Decimal(100)
    assert len(dividends) == 1
    assert dividends[0].business_year == 2024
    assert audit is not None
    assert audit.business_year == 2024
    assert audit.opinion == "적정"


def test_latest_financial_period_does_not_backfill_missing_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(
        tmp_path / "phase2-financial-period.db",
        monkeypatch,
    )
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    collected_at = datetime(2026, 7, 29, 15, 30, tzinfo=SEOUL)

    with sessions.begin() as session:
        stock = Stock(
            symbol="000012",
            name_ko="재무기간검증",
            is_active=True,
            source_provider="KRX",
            source_function="test fixture",
            data_state="AVAILABLE",
            as_of_at=collected_at,
            collected_at=collected_at,
        )
        session.add(stock)
        session.flush()
        for year, report_code, receipt, metric, amount in (
            (
                2025,
                "11011",
                "20260331000004",
                "OPERATING_PROFIT",
                Decimal(50),
            ),
            (
                2026,
                "11013",
                "20260515000004",
                "REVENUE",
                Decimal(200),
            ),
        ):
            statement = FinancialStatement(
                stock_id=stock.id,
                corp_code="00126380",
                receipt_no=receipt,
                report_code=report_code,
                business_year=year,
                statement_kind="IS",
                fs_div="CFS",
                filing_date=(
                    date(2026, 3, 31)
                    if report_code == "11011"
                    else date(2026, 5, 15)
                ),
                source_provider="OpenDART",
                source_function="test fixture",
                data_state="AVAILABLE",
                collected_at=collected_at,
                data_timing="PERIODIC_DISCLOSURE",
            )
            session.add(statement)
            session.flush()
            session.add(
                FinancialAccount(
                    statement_id=statement.id,
                    account_id=f"test-{metric}",
                    account_name=metric,
                    statement_section="IS",
                    amount=amount,
                    current_amount=amount,
                    current_cumulative_amount=amount,
                    unit="KRW",
                    canonical_metric_code=metric,
                    mapping_status="MAPPED",
                )
            )
        stock_id = stock.id

    with sessions() as session:
        scope, accounts = FinancialRepository().latest_mapped_accounts(
            session,
            stock_id,
            as_of_date=date(2026, 7, 29),
        )

    engine.dispose()
    assert scope == FinancialScope.CONSOLIDATED
    assert {account.metric_code for account in accounts} == {"REVENUE"}


def test_scoring_repository_persists_explainable_result_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "phase2-score.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    result = evaluate_phase2(_valid_evidence(), Phase2Rules())
    repository = ScoringRepository()

    with sessions.begin() as session:
        stock = Stock(
            symbol="000001",
            name_ko="검증종목",
            source_provider="KRX",
            source_function="test fixture",
            data_state="AVAILABLE",
            collected_at=result.as_of_at,
        )
        session.add(stock)
        session.flush()
        first = repository.save(session, stock.id, result)
        second = repository.save(session, stock.id, result)
        assert first.id == second.id

    with sessions() as session:
        snapshot = session.query(ScoreSnapshot).one()
        assert snapshot.investment_score == result.investment_score
        assert snapshot.entry_score is None
        assert (
            snapshot.individual_entry_score
            == result.individual_entry_score
        )
        assert snapshot.recommendation_computable is True
        assert session.query(ForcedFilterResult).count() == len(result.filters)
        assert (
            session.query(ScoreComponentRecord).count()
            == len(result.components)
        )
        assert (
            session.query(ValuationComparisonRecord).count()
            == len(result.valuation_comparisons)
        )
        restored = repository.latest(session, stock.id)

    engine.dispose()
    assert restored == result


def test_scoring_repository_does_not_convert_legacy_missing_confidence_to_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(
        tmp_path / "phase2-legacy-score.db",
        monkeypatch,
    )
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    as_of_at = datetime(2026, 7, 29, 15, 30, tzinfo=SEOUL)

    with sessions.begin() as session:
        stock = Stock(
            symbol="000005",
            name_ko="구버전점수",
            source_provider="KRX",
            source_function="test fixture",
            data_state="AVAILABLE",
            collected_at=as_of_at,
        )
        session.add(stock)
        session.flush()
        session.add(
            ScoreSnapshot(
                stock_id=stock.id,
                as_of_at=as_of_at,
                score_version="legacy",
                rule_version="legacy",
                input_data_hash="a" * 64,
                data_confidence=None,
                data_state="MISSING",
                score_scope="PHASE1_LEGACY",
                filter_state="NOT_VERIFIED",
                recommendation_computable=False,
                missing_core_data=["LEGACY"],
                explanation="legacy row",
            )
        )

    with sessions() as session:
        stock = session.query(Stock).filter_by(symbol="000005").one()
        restored = ScoringRepository().latest(session, stock.id)

    engine.dispose()
    assert restored is None


def test_phase2_service_persists_missing_evidence_without_fake_score(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(
        tmp_path / "phase2-service-missing.db",
        monkeypatch,
    )
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    as_of_at = datetime(2026, 7, 29, 15, 30, tzinfo=SEOUL)
    with sessions.begin() as session:
        session.add(
            Stock(
                symbol="000006",
                name_ko="누락검증종목",
                is_kospi=True,
                security_type="STOCK",
                share_class="COMMON",
                listing_status="LISTED",
                is_active=True,
                source_provider="KRX",
                source_function="test fixture",
                data_state="AVAILABLE",
                as_of_at=as_of_at,
                collected_at=as_of_at,
            )
        )
    engine.dispose()

    service = Phase2ScoringService(settings)
    try:
        result = service.evaluate(
            "000006",
            as_of_at=as_of_at,
            planned_order_amount=Decimal(1000000),
        )
        restored = service.latest("000006")
    finally:
        service.close()

    assert result is not None
    assert restored == result
    assert result.investment_score is None
    assert result.individual_entry_score is None
    assert result.recommendation_computable is False
    assert any(item.state == FilterState.MISSING for item in result.filters)
    assert result.data_state == DataState.MISSING
    confidence_components = {
        item.code: item
        for item in result.components
        if item.score_name == "DATA_CONFIDENCE"
    }
    assert (
        confidence_components["ACCOUNT_MAPPING"].state
        == ComponentState.MISSING
    )
    assert (
        confidence_components["ADJUSTED_PRICE"].state
        == ComponentState.MISSING
    )
