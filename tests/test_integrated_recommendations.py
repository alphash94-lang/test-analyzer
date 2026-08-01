from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import get_settings
from app.db.models.event import EventRecord, NewsArticle
from app.db.models.financial import FinancialAccount, FinancialStatement
from app.db.models.market import PriceDaily, Stock
from app.db.session import create_db_engine, create_session_factory
from app.models.market_analysis import MarketRegime
from app.models.metadata import DataState
from app.models.recommendation import (
    HoldingAction,
    PortfolioSleeve,
    RecommendationCategory,
    RecommendationDecision,
)
from app.services.integrated_recommendation_service import (
    IntegratedRecommendationService,
)
from app.utils.dates import SEOUL
from tests.helpers import migrate_database

AS_OF = datetime(2026, 7, 31, 18, tzinfo=SEOUL)


def _decision(stock_id: int, symbol: str) -> RecommendationDecision:
    return RecommendationDecision(
        stock_id=stock_id,
        symbol=symbol,
        name=f"종목{stock_id}",
        category=RecommendationCategory.QUALITY_WAIT,
        category_label="우량하지만 관망",
        score_scope="TEST",
        investment_score=Decimal(70),
        entry_score=Decimal(60),
        entry_score_scope="TEST",
        data_confidence=Decimal(90),
        market_regime=MarketRegime.GREEN,
        sleeve=PortfolioSleeve.DIVIDEND,
        holding_action=HoldingAction.WAIT,
        positive_reasons=(),
        risk_reasons=(),
        exclusion_reasons=(),
        missing_data=(),
        raw_metrics={},
        filter_results=(),
    )


def _event(
    stock_id: int,
    *,
    sentiment: str,
    matched_rule: str,
    source_kind: str = "DISCLOSURE",
) -> EventRecord:
    return EventRecord(
        stock_id=stock_id,
        source_provider="OpenDART" if source_kind == "DISCLOSURE" else "Naver",
        source_kind=source_kind,
        source_record_key=f"{stock_id}-{matched_rule}",
        title=f"event-{matched_rule}",
        event_type=matched_rule,
        published_at=AS_OF,
        collected_at=AS_OF,
        sentiment=sentiment,
        confidence="HIGH" if source_kind == "DISCLOSURE" else "MEDIUM",
        rationale="structured test signal",
        matched_rule=matched_rule,
        used_text_scope="DISCLOSURE_TITLE_ONLY",
        used_text="test",
        price_reflection_note="not verified",
        rule_version="phase5-event-rule-v1",
        data_state=DataState.AVAILABLE.value,
        is_correction=False,
        correction_link_state="NOT_APPLICABLE",
    )


def _add_financials(session, stock_id: int) -> None:
    statement = FinancialStatement(
        stock_id=stock_id,
        corp_code=f"{stock_id:08d}",
        receipt_no=f"20260515{stock_id:06d}",
        report_name="1분기보고서",
        report_code="11013",
        business_year=2026,
        statement_kind="CIS",
        fs_div="CFS",
        filing_date=AS_OF.date(),
        source_provider="OpenDART",
        source_function="TEST",
        data_state=DataState.AVAILABLE.value,
        collected_at=AS_OF,
    )
    session.add(statement)
    session.flush()
    for code, current, prior in (
        ("REVENUE", Decimal(120), Decimal(100)),
        ("OPERATING_PROFIT", Decimal(15), Decimal(10)),
        ("PARENT_OWNERS_NET_INCOME", Decimal(12), Decimal(8)),
    ):
        session.add(
            FinancialAccount(
                statement_id=statement.id,
                account_id=code,
                account_name=code,
                account_detail="",
                statement_section="CIS",
                current_amount=current,
                current_cumulative_amount=current,
                prior_cumulative_amount=prior,
                canonical_metric_code=code,
                mapping_status="MAPPED",
            )
        )


def test_integrated_ranking_rewards_positive_and_penalizes_negative_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "integrated.db", monkeypatch)
    settings = get_settings().model_copy(update={"database_url": database_url})
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        session.add_all(
            [
                Stock(
                    id=1,
                    symbol="000001",
                    name_ko="긍정종목",
                    is_active=True,
                    source_provider="KRX",
                    source_function="TEST",
                    data_state=DataState.AVAILABLE.value,
                    collected_at=AS_OF,
                ),
                Stock(
                    id=2,
                    symbol="000002",
                    name_ko="부정종목",
                    is_active=True,
                    source_provider="KRX",
                    source_function="TEST",
                    data_state=DataState.AVAILABLE.value,
                    collected_at=AS_OF,
                ),
            ]
        )
        session.flush()
        _add_financials(session, 1)
        _add_financials(session, 2)
        session.add(_event(1, sentiment="POSITIVE", matched_rule="LARGE_CONTRACT"))
        session.add(
            _event(
                2,
                sentiment="NEGATIVE",
                matched_rule="OPERATING_LOSS",
                source_kind="NEWS",
            )
        )
    engine.dispose()

    service = IntegratedRecommendationService(settings)
    try:
        results = service.build(
            (_decision(1, "000001"), _decision(2, "000002")),
            basis_date=AS_OF.date(),
        )
    finally:
        service.close()

    assert [item.decision.symbol for item in results] == ["000001", "000002"]
    assert results[0].nonfinancial_score > Decimal(50)
    assert results[1].nonfinancial_score < Decimal(50)
    assert results[0].combined_score > results[1].combined_score


def test_integrated_ranking_excludes_severe_disclosure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "integrated-severe.db", monkeypatch)
    settings = get_settings().model_copy(update={"database_url": database_url})
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        session.add(
            Stock(
                id=3,
                symbol="000003",
                name_ko="위험종목",
                is_active=True,
                source_provider="KRX",
                source_function="TEST",
                data_state=DataState.AVAILABLE.value,
                collected_at=AS_OF,
            )
        )
        session.flush()
        _add_financials(session, 3)
        session.add(
            _event(3, sentiment="NEGATIVE", matched_rule="AUDIT_RISK")
        )
    engine.dispose()

    service = IntegratedRecommendationService(settings)
    try:
        result = service.build(
            (_decision(3, "000003"),),
            basis_date=AS_OF.date(),
        )[0]
    finally:
        service.close()

    assert result.eligible is False
    assert result.nonfinancial_score == 0
    assert result.status_label == "중대 위험 공시로 제외"


def test_integrated_ranking_does_not_hard_exclude_news_keyword(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "integrated-news.db", monkeypatch)
    settings = get_settings().model_copy(update={"database_url": database_url})
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        session.add(
            Stock(
                id=4,
                symbol="000004",
                name_ko="뉴스주의종목",
                is_active=True,
                source_provider="KRX",
                source_function="TEST",
                data_state=DataState.AVAILABLE.value,
                collected_at=AS_OF,
            )
        )
        session.flush()
        _add_financials(session, 4)
        session.add(
            _event(
                4,
                sentiment="NEGATIVE",
                matched_rule="SANCTION",
                source_kind="NEWS",
            )
        )
    engine.dispose()

    service = IntegratedRecommendationService(settings)
    try:
        result = service.build(
            (_decision(4, "000004"),),
            basis_date=AS_OF.date(),
        )[0]
    finally:
        service.close()

    assert result.eligible is True
    assert result.nonfinancial_score < 50


def test_integrated_result_includes_naver_news_summaries_and_directions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "integrated-news-evidence.db", monkeypatch)
    settings = get_settings().model_copy(update={"database_url": database_url})
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        session.add(
            Stock(
                id=5,
                symbol="000005",
                name_ko="뉴스근거종목",
                is_active=True,
                source_provider="KRX",
                source_function="TEST",
                data_state=DataState.AVAILABLE.value,
                collected_at=AS_OF,
            )
        )
        session.flush()
        _add_financials(session, 5)
        for index, (sentiment, rule, title, summary) in enumerate(
            (
                ("POSITIVE", "LARGE_CONTRACT", "대형 수주 체결", "해외 고객과 공급 계약을 맺었습니다."),
                ("NEGATIVE", "OPERATING_LOSS", "영업손실 발생", "분기 영업손실이 발생했습니다."),
            ),
            start=1,
        ):
            content_hash = f"news-hash-{index}"
            event = _event(
                5,
                sentiment=sentiment,
                matched_rule=rule,
                source_kind="NEWS",
            )
            event.source_record_key = content_hash
            event.title = title
            event.source_url = f"https://news.example.test/{index}"
            session.add(event)
            session.add(
                NewsArticle(
                    stock_id=5,
                    query="뉴스근거종목",
                    title=title,
                    summary=summary,
                    provider_url=f"https://n.news.naver.com/article/001/{index}",
                    canonical_url=f"https://news.example.test/{index}",
                    normalized_title=title,
                    content_hash=content_hash,
                    published_at=AS_OF - timedelta(hours=index),
                    used_text_scope="TITLE_AND_PROVIDED_SUMMARY",
                    source_provider="Naver API HUB",
                    source_function="네이버 뉴스 검색 API",
                    data_state=DataState.AVAILABLE.value,
                    as_of_at=AS_OF - timedelta(hours=index),
                    collected_at=AS_OF,
                    data_timing="DELAYED",
                )
            )
    engine.dispose()

    service = IntegratedRecommendationService(settings)
    try:
        result = service.build(
            (_decision(5, "000005"),),
            basis_date=AS_OF.date(),
        )[0]
    finally:
        service.close()

    assert [news.title for news in result.news_evidences] == [
        "대형 수주 체결",
        "영업손실 발생",
    ]
    assert [news.sentiment for news in result.news_evidences] == [
        "POSITIVE",
        "NEGATIVE",
    ]
    assert result.news_evidences[0].summary == "해외 고객과 공급 계약을 맺었습니다."
    assert result.news_evidences[0].source_url == (
        "https://n.news.naver.com/article/001/1"
    )


def test_liquid_quality_uses_marketwide_20_session_trading_value_rank(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "liquid-quality.db", monkeypatch)
    settings = get_settings().model_copy(update={"database_url": database_url})
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        session.add_all(
            [
                Stock(
                    id=10,
                    symbol="000010",
                    name_ko="활발종목",
                    is_active=True,
                    source_provider="KRX",
                    source_function="TEST",
                    data_state=DataState.AVAILABLE.value,
                    collected_at=AS_OF,
                ),
                Stock(
                    id=11,
                    symbol="000011",
                    name_ko="잠자는종목",
                    is_active=True,
                    source_provider="KRX",
                    source_function="TEST",
                    data_state=DataState.AVAILABLE.value,
                    collected_at=AS_OF,
                ),
            ]
        )
        session.flush()
        for stock_id in (10, 11):
            _add_financials(session, stock_id)
            if stock_id == 10:
                session.add(
                    _event(
                        stock_id,
                        sentiment="POSITIVE",
                        matched_rule="LARGE_CONTRACT",
                    )
                )
            for offset in range(20):
                session.add(
                    PriceDaily(
                        stock_id=stock_id,
                        trade_date=AS_OF.date() - timedelta(days=offset),
                        trading_value=(
                            Decimal(5_000_000_000)
                            if stock_id == 10
                            else Decimal(100_000_000)
                        ),
                        source_provider="KRX",
                        source_function="TEST",
                        data_state=DataState.AVAILABLE.value,
                        collected_at=AS_OF,
                    )
                )
    engine.dispose()

    liquid_high = _decision(10, "000010").model_copy(
        update={"category": RecommendationCategory.EXCLUDED}
    )
    liquid_low = _decision(11, "000011")
    service = IntegratedRecommendationService(settings)
    try:
        candidates = service.liquid_candidates(
            (liquid_high, liquid_low),
            basis_date=AS_OF.date(),
            minimum_median_trading_value=Decimal(1_000_000_000),
        )
        results = service.build_liquid_quality(
            (liquid_high, liquid_low),
            basis_date=AS_OF.date(),
            minimum_median_trading_value=Decimal(1_000_000_000),
        )
    finally:
        service.close()

    assert [item.decision.symbol for item in candidates] == [
        "000010",
        "000011",
    ]
    assert results[0].integrated.decision.symbol == "000010"
    assert results[0].trading_value_rank == 1
    assert results[0].observed_sessions == 20
    assert results[0].eligible is True
    assert results[1].eligible is False
    assert results[1].integrated.has_nonfinancial_data is False
    assert results[1].integrated.nonfinancial_score == 50
    assert results[1].status_label == "20일 중앙 거래대금 기준 미달"
