from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from statistics import median

from sqlalchemy import case, func, select

from app.config import Settings
from app.db.models.disclosure import Disclosure
from app.db.models.event import EventRecord, NewsArticle
from app.db.models.financial import FinancialAccount, FinancialStatement
from app.db.models.market import PriceDaily
from app.db.session import create_db_engine, create_session_factory
from app.models.metadata import DataState
from app.models.recommendation import (
    RecommendationCategory,
    RecommendationDecision,
)
from app.utils.dates import SEOUL, restore_database_kst

INTEGRATED_RULE_VERSION = "integrated-recommendation-rule-v1"
FINANCIAL_WEIGHT = Decimal("0.70")
NONFINANCIAL_WEIGHT = Decimal("0.30")
EVENT_LOOKBACK_DAYS = 90
NEWS_EVIDENCE_LIMIT = 5
INTEGRATED_MINIMUM_SCORE = Decimal(60)
LIQUID_QUALITY_RULE_VERSION = "liquid-quality-recommendation-v1"
LIQUIDITY_WEIGHT = Decimal("0.40")
LIQUID_QUALITY_FINANCIAL_WEIGHT = Decimal("0.42")
LIQUID_QUALITY_NONFINANCIAL_WEIGHT = Decimal("0.18")
LIQUIDITY_LOOKBACK_SESSIONS = 20
LIQUIDITY_MINIMUM_SESSIONS = 10
LIQUIDITY_POOL_MAX_RANK = 100

_SEVERE_RULES = frozenset(
    {
        "DEFAULT_INSOLVENCY",
        "REHABILITATION",
        "DISSOLUTION",
        "BUSINESS_SUSPENSION",
        "DELISTING",
        "EMBEZZLEMENT_BREACH",
        "AUDIT_RISK",
        "SANCTION",
    }
)
_CONFIDENCE_WEIGHT = {
    "HIGH": Decimal("1.00"),
    "MEDIUM": Decimal("0.65"),
    "LOW": Decimal("0.25"),
    "UNVERIFIED": Decimal(0),
}
_SOURCE_WEIGHT = {
    "DISCLOSURE": Decimal("1.25"),
    "NEWS": Decimal("0.50"),
}
_NEGATIVE_HEADLINE_CUES = (
    "하락",
    "급락",
    "약세",
    "감소",
    "적자",
    "부진",
    "중단",
)


@dataclass(frozen=True)
class IntegratedEventEvidence:
    title: str
    source_kind: str
    sentiment: str
    published_date: date
    rationale: str
    contribution: Decimal
    source_url: str | None


@dataclass(frozen=True)
class IntegratedNewsEvidence:
    title: str
    summary: str
    published_date: date
    sentiment: str
    rationale: str
    source_url: str


@dataclass(frozen=True)
class IntegratedRecommendation:
    decision: RecommendationDecision
    combined_score: Decimal
    valuation_score: Decimal
    earnings_trend_score: Decimal | None
    financial_score: Decimal
    financial_period: date | None
    financial_reason: str
    nonfinancial_score: Decimal
    has_nonfinancial_data: bool
    news_article_count: int
    disclosure_count: int
    signal_count: int
    coverage_label: str
    status_label: str
    eligible: bool
    evidences: tuple[IntegratedEventEvidence, ...]
    news_evidences: tuple[IntegratedNewsEvidence, ...] = ()


@dataclass(frozen=True)
class LiquidQualityRecommendation:
    integrated: IntegratedRecommendation
    trading_value_rank: int
    trading_value_universe_count: int
    median_trading_value: Decimal
    observed_sessions: int
    liquidity_score: Decimal
    quality_score: Decimal
    eligible: bool
    status_label: str


@dataclass(frozen=True)
class LiquidCandidate:
    decision: RecommendationDecision
    trading_value_rank: int
    median_trading_value: Decimal
    observed_sessions: int


@dataclass(frozen=True)
class _FinancialTrend:
    period_end: date
    revenue: Decimal | None
    prior_revenue: Decimal | None
    operating_profit: Decimal | None
    prior_operating_profit: Decimal | None
    net_income: Decimal | None
    prior_net_income: Decimal | None


def _clamp(value: Decimal, minimum: Decimal, maximum: Decimal) -> Decimal:
    return min(max(value, minimum), maximum)


def _recency_weight(days_old: int) -> Decimal:
    if days_old <= 7:
        return Decimal("1.00")
    if days_old <= 30:
        return Decimal("0.80")
    if days_old <= 60:
        return Decimal("0.50")
    return Decimal("0.25")


def _event_contribution(row: EventRecord, *, basis_date: date) -> Decimal:
    if row.sentiment not in {"POSITIVE", "NEGATIVE"}:
        return Decimal(0)
    if (
        row.source_kind == "NEWS"
        and row.sentiment == "POSITIVE"
        and any(cue in row.title for cue in _NEGATIVE_HEADLINE_CUES)
    ):
        return Decimal(0)
    published = restore_database_kst(row.published_at).date()
    days_old = max((basis_date - published).days, 0)
    magnitude = (
        Decimal(18)
        * _CONFIDENCE_WEIGHT.get(row.confidence, Decimal(0))
        * _SOURCE_WEIGHT.get(row.source_kind, Decimal("0.50"))
        * _recency_weight(days_old)
    )
    if row.sentiment == "NEGATIVE":
        return -(magnitude * Decimal("1.20"))
    return magnitude


def _change_score(current: Decimal | None, prior: Decimal | None) -> Decimal:
    if current is None or prior is None:
        return Decimal(0)
    if prior <= 0 < current:
        return Decimal(15)
    if current <= 0 < prior:
        return Decimal(-15)
    if current <= 0 and prior <= 0:
        return (
            Decimal(10)
            if current > prior
            else Decimal(-10)
            if current < prior
            else Decimal(0)
        )
    if prior == 0:
        return Decimal(0)
    growth = current / abs(prior) - Decimal(1)
    if growth >= Decimal("0.10"):
        return Decimal(10)
    if growth >= 0:
        return Decimal(5)
    if growth > Decimal("-0.10"):
        return Decimal(-5)
    return Decimal(-10)


def _earnings_trend_score(trend: _FinancialTrend) -> tuple[Decimal, str]:
    score = Decimal(50)
    revenue_change = _change_score(trend.revenue, trend.prior_revenue)
    score += revenue_change
    if trend.operating_profit is not None:
        score += Decimal(10) if trend.operating_profit > 0 else Decimal(-20)
    score += _change_score(trend.operating_profit, trend.prior_operating_profit)
    if trend.net_income is not None:
        score += Decimal(10) if trend.net_income > 0 else Decimal(-25)
    score += _change_score(trend.net_income, trend.prior_net_income)
    normalized = _clamp(score, Decimal(0), Decimal(100)).quantize(
        Decimal("0.001")
    )

    def direction(current: Decimal | None, prior: Decimal | None) -> str:
        change = _change_score(current, prior)
        return "개선" if change > 0 else "둔화" if change < 0 else "비교 제한"

    reason = (
        f"매출 {direction(trend.revenue, trend.prior_revenue)}, "
        f"영업이익 {direction(trend.operating_profit, trend.prior_operating_profit)}, "
        f"순이익 {direction(trend.net_income, trend.prior_net_income)}"
    )
    return normalized, reason


def _has_hard_filter_failure(decision: RecommendationDecision) -> bool:
    return any(
        str(result.get("state", "")).upper() == "FAIL"
        for result in decision.filter_results
    )


class IntegratedRecommendationService:
    """Blend financially screened candidates with stored news/disclosures."""

    def __init__(self, settings: Settings) -> None:
        self._engine = create_db_engine(settings)
        self._sessions = create_session_factory(self._engine)

    def build(
        self,
        decisions: tuple[RecommendationDecision, ...],
        *,
        basis_date: date,
        include_score_excluded: bool = False,
        retain_missing_events: bool = False,
        allow_incomplete_financial: bool = False,
    ) -> tuple[IntegratedRecommendation, ...]:
        candidates = tuple(
            item
            for item in decisions
            if item.category != RecommendationCategory.INSUFFICIENT_DATA
            and (
                item.category != RecommendationCategory.EXCLUDED
                or (
                    include_score_excluded
                    and not _has_hard_filter_failure(item)
                )
            )
            and item.investment_score is not None
        )
        if not candidates:
            return ()
        candidate_ids = [item.stock_id for item in candidates]
        start_at = datetime.combine(
            basis_date - timedelta(days=EVENT_LOOKBACK_DAYS),
            time.min,
            tzinfo=SEOUL,
        )
        end_at = datetime.combine(
            basis_date + timedelta(days=1),
            time.min,
            tzinfo=SEOUL,
        )
        with self._sessions() as session:
            rows = session.scalars(
                select(EventRecord)
                .where(
                    EventRecord.stock_id.in_(candidate_ids),
                    EventRecord.data_state == DataState.AVAILABLE.value,
                    EventRecord.published_at >= start_at,
                    EventRecord.published_at < end_at,
                )
                .order_by(
                    EventRecord.stock_id,
                    EventRecord.published_at.desc(),
                    EventRecord.id.desc(),
                )
            ).all()
            financial_trends = self._financial_trends(
                session,
                candidate_ids,
                basis_date=basis_date,
            )
            news_counts = {
                stock_id: count
                for stock_id, count in session.execute(
                    select(NewsArticle.stock_id, func.count(NewsArticle.id))
                    .where(
                        NewsArticle.stock_id.in_(candidate_ids),
                        NewsArticle.data_state == DataState.AVAILABLE.value,
                        NewsArticle.published_at >= start_at,
                        NewsArticle.published_at < end_at,
                    )
                    .group_by(NewsArticle.stock_id)
                ).tuples()
            }
            ranked_news = (
                select(
                    NewsArticle.id.label("news_id"),
                    func.row_number()
                    .over(
                        partition_by=NewsArticle.stock_id,
                        order_by=(
                            NewsArticle.published_at.desc(),
                            NewsArticle.id.desc(),
                        ),
                    )
                    .label("news_rank"),
                )
                .where(
                    NewsArticle.stock_id.in_(candidate_ids),
                    NewsArticle.data_state == DataState.AVAILABLE.value,
                    NewsArticle.published_at >= start_at,
                    NewsArticle.published_at < end_at,
                )
                .subquery()
            )
            news_rows = session.scalars(
                select(NewsArticle)
                .join(ranked_news, NewsArticle.id == ranked_news.c.news_id)
                .where(ranked_news.c.news_rank <= NEWS_EVIDENCE_LIMIT)
                .order_by(
                    NewsArticle.stock_id,
                    NewsArticle.published_at.desc(),
                    NewsArticle.id.desc(),
                )
            ).all()
            disclosure_counts = {
                stock_id: count
                for stock_id, count in session.execute(
                    select(Disclosure.stock_id, func.count(Disclosure.id))
                    .where(
                        Disclosure.stock_id.in_(candidate_ids),
                        Disclosure.data_state == DataState.AVAILABLE.value,
                        Disclosure.receipt_date
                        >= basis_date - timedelta(days=EVENT_LOOKBACK_DAYS),
                        Disclosure.receipt_date <= basis_date,
                    )
                    .group_by(Disclosure.stock_id)
                ).tuples()
                if stock_id is not None
            }

        by_stock: dict[int, list[EventRecord]] = {}
        seen: dict[int, set[tuple[str, str, str]]] = {}
        for row in rows:
            if row.stock_id is None:
                continue
            key = (row.source_kind, row.event_type, row.matched_rule)
            stock_seen = seen.setdefault(row.stock_id, set())
            if key in stock_seen or len(by_stock.get(row.stock_id, [])) >= 6:
                continue
            stock_seen.add(key)
            by_stock.setdefault(row.stock_id, []).append(row)

        news_event_by_source = {
            (row.stock_id, row.source_record_key): row
            for row in rows
            if row.stock_id is not None and row.source_kind == "NEWS"
        }
        news_by_stock: dict[int, list[IntegratedNewsEvidence]] = {}
        for article in news_rows:
            event = news_event_by_source.get(
                (article.stock_id, article.content_hash)
            )
            news_by_stock.setdefault(article.stock_id, []).append(
                IntegratedNewsEvidence(
                    title=article.title,
                    summary=article.summary,
                    published_date=restore_database_kst(
                        article.published_at
                    ).date(),
                    sentiment=(
                        event.sentiment if event is not None else "UNCLASSIFIED"
                    ),
                    rationale=(
                        event.rationale
                        if event is not None
                        else "저장된 기사에 연결된 구조화 판정이 없습니다."
                    ),
                    source_url=article.original_url or article.provider_url,
                )
            )

        results: list[IntegratedRecommendation] = []
        for decision in candidates:
            event_rows = by_stock.get(decision.stock_id, [])
            if not event_rows and not retain_missing_events:
                continue
            contributions = [
                _event_contribution(row, basis_date=basis_date)
                for row in event_rows
            ]
            signal = sum(contributions, start=Decimal(0))
            severe = any(
                row.source_kind == "DISCLOSURE"
                and row.sentiment == "NEGATIVE"
                and row.confidence == "HIGH"
                and row.matched_rule in _SEVERE_RULES
                for row in event_rows
            )
            nonfinancial = (
                Decimal(0)
                if severe
                else _clamp(
                    Decimal(50) + signal,
                    Decimal(0),
                    Decimal(100),
                )
            ).quantize(Decimal("0.001"))
            assert decision.investment_score is not None
            trend = financial_trends.get(decision.stock_id)
            if trend is None:
                earnings_score = None
                financial = decision.investment_score
                financial_reason = "최신 분기·연간 실적의 전년 동기 비교자료가 없습니다."
            else:
                earnings_score, financial_reason = _earnings_trend_score(trend)
                financial = (
                    decision.investment_score * Decimal("0.55")
                    + earnings_score * Decimal("0.45")
                ).quantize(Decimal("0.001"))
            combined = (
                financial * FINANCIAL_WEIGHT
                + nonfinancial * NONFINANCIAL_WEIGHT
            ).quantize(Decimal("0.001"))
            news_count = int(news_counts.get(decision.stock_id, 0))
            disclosure_count = int(
                disclosure_counts.get(decision.stock_id, 0)
            )
            has_nonfinancial_data = bool(
                event_rows or news_count or disclosure_count
            )
            coverage = (
                f"뉴스 {news_count}건 · 공시 {disclosure_count}건 · "
                f"점수반영 신호 {len(event_rows)}건"
                if has_nonfinancial_data
                else "뉴스·공시 원문 미수집"
            )
            status = (
                "중대 위험 공시로 제외"
                if severe
                else "최신 실적 추세 미확인"
                if trend is None
                else "종합 기준 60점 미달"
                if combined < INTEGRATED_MINIMUM_SCORE
                else "긍정 신호 우세"
                if signal > Decimal(5)
                else "주의 신호 우세"
                if signal < Decimal(-5)
                else "뚜렷한 방향 없음"
            )
            evidences = tuple(
                IntegratedEventEvidence(
                    title=row.title,
                    source_kind=row.source_kind,
                    sentiment=row.sentiment,
                    published_date=restore_database_kst(row.published_at).date(),
                    rationale=row.rationale,
                    contribution=contribution.quantize(Decimal("0.001")),
                    source_url=row.source_url,
                )
                for row, contribution in zip(
                    event_rows,
                    contributions,
                    strict=True,
                )
            )
            results.append(
                IntegratedRecommendation(
                    decision=decision,
                    combined_score=combined,
                    valuation_score=decision.investment_score,
                    earnings_trend_score=earnings_score,
                    financial_score=financial,
                    financial_period=(trend.period_end if trend is not None else None),
                    financial_reason=financial_reason,
                    nonfinancial_score=nonfinancial,
                    has_nonfinancial_data=has_nonfinancial_data,
                    news_article_count=news_count,
                    disclosure_count=disclosure_count,
                    signal_count=len(event_rows),
                    coverage_label=coverage,
                    status_label=status,
                    eligible=(
                        not severe
                        and (trend is not None or allow_incomplete_financial)
                        and combined >= INTEGRATED_MINIMUM_SCORE
                    ),
                    evidences=evidences,
                    news_evidences=tuple(news_by_stock.get(decision.stock_id, [])),
                )
            )
        return tuple(
            sorted(
                results,
                key=lambda item: (
                    item.eligible,
                    item.combined_score,
                    item.financial_score,
                ),
                reverse=True,
            )
        )

    def build_liquid_quality(
        self,
        decisions: tuple[RecommendationDecision, ...],
        *,
        basis_date: date,
        minimum_median_trading_value: Decimal,
    ) -> tuple[LiquidQualityRecommendation, ...]:
        """Rank liquid stocks first, then blend financial and event quality.

        The liquidity rank is calculated across the recommendation universe
        after hard-risk filters. A 20-session median is used so one exceptional
        trading day cannot make a dormant stock look liquid.
        """
        integrated = self.build(
            decisions,
            basis_date=basis_date,
            include_score_excluded=True,
            retain_missing_events=True,
            allow_incomplete_financial=True,
        )
        if not integrated:
            return ()

        liquid_pool = self.liquid_candidates(
            decisions,
            basis_date=basis_date,
            minimum_median_trading_value=minimum_median_trading_value,
        )
        universe_count = len(liquid_pool)
        liquidity_by_stock = {
            item.decision.stock_id: (
                item.trading_value_rank,
                item.median_trading_value,
                item.observed_sessions,
                (
                    Decimal(100)
                    if universe_count <= 1
                    else (
                        Decimal(universe_count - item.trading_value_rank)
                        / Decimal(universe_count - 1)
                        * Decimal(100)
                    ).quantize(Decimal("0.001"))
                ),
            )
            for item in liquid_pool
        }

        results: list[LiquidQualityRecommendation] = []
        for item in integrated:
            liquidity = liquidity_by_stock.get(item.decision.stock_id)
            if liquidity is None:
                continue
            rank, median_value, sessions, liquidity_score = liquidity
            quality_score = (
                item.financial_score * FINANCIAL_WEIGHT
                + item.nonfinancial_score * NONFINANCIAL_WEIGHT
            ).quantize(Decimal("0.001"))
            liquid_enough = (
                rank <= LIQUIDITY_POOL_MAX_RANK
                and median_value >= minimum_median_trading_value
            )
            severe = item.status_label == "중대 위험 공시로 제외"
            confidence_ok = (
                item.decision.data_confidence is not None
                and item.decision.data_confidence >= Decimal(70)
            )
            eligible = liquid_enough and not severe and confidence_ok
            status = (
                "중대 위험 공시로 제외"
                if severe
                else "20일 중앙 거래대금 기준 미달"
                if median_value < minimum_median_trading_value
                else "데이터 신뢰도 70점 미달"
                if not confidence_ok
                else "잠정 추천·상세 재무와 비재무 보강 필요"
                if item.earnings_trend_score is None
                or not item.has_nonfinancial_data
                else "거래대금 100위·종합평가 완료"
            )
            results.append(
                LiquidQualityRecommendation(
                    integrated=item,
                    trading_value_rank=rank,
                    trading_value_universe_count=universe_count,
                    median_trading_value=median_value,
                    observed_sessions=sessions,
                    liquidity_score=liquidity_score,
                    quality_score=quality_score,
                    eligible=eligible,
                    status_label=status,
                )
            )
        return tuple(
            sorted(
                results,
                key=lambda item: (
                    item.eligible,
                    item.quality_score,
                    -item.trading_value_rank,
                ),
                reverse=True,
            )
        )

    def liquid_candidates(
        self,
        decisions: tuple[RecommendationDecision, ...],
        *,
        basis_date: date,
        minimum_median_trading_value: Decimal,
    ) -> tuple[LiquidCandidate, ...]:
        """Return the top 100 valid common stocks in liquidity order."""
        liquidity_by_stock, _ = self._liquidity_statistics(basis_date=basis_date)
        unranked: list[tuple[RecommendationDecision, Decimal, int]] = []
        for decision in decisions:
            if (
                decision.category == RecommendationCategory.INSUFFICIENT_DATA
                or _has_hard_filter_failure(decision)
                or decision.investment_score is None
            ):
                continue
            liquidity = liquidity_by_stock.get(decision.stock_id)
            if liquidity is None:
                continue
            _, median_value, sessions, _ = liquidity
            unranked.append((decision, median_value, sessions))
        unranked.sort(key=lambda item: item[1], reverse=True)
        return tuple(
            LiquidCandidate(
                decision=decision,
                trading_value_rank=rank,
                median_trading_value=median_value,
                observed_sessions=sessions,
            )
            for rank, (decision, median_value, sessions) in enumerate(
                unranked[:LIQUIDITY_POOL_MAX_RANK],
                start=1,
            )
        )

    def _liquidity_statistics(
        self,
        *,
        basis_date: date,
    ) -> tuple[dict[int, tuple[int, Decimal, int, Decimal]], int]:
        start_date = basis_date - timedelta(days=45)
        with self._sessions() as session:
            price_rows = session.execute(
                select(
                    PriceDaily.stock_id,
                    PriceDaily.trade_date,
                    PriceDaily.trading_value,
                )
                .where(
                    PriceDaily.trade_date >= start_date,
                    PriceDaily.trade_date <= basis_date,
                    PriceDaily.source_provider == "KRX",
                    PriceDaily.data_state == DataState.AVAILABLE.value,
                    PriceDaily.trading_value.is_not(None),
                )
                .order_by(PriceDaily.stock_id, PriceDaily.trade_date.desc())
            ).all()
        values_by_stock: dict[int, list[Decimal]] = {}
        dates_by_stock: dict[int, set[date]] = {}
        for stock_id, trade_date, trading_value in price_rows:
            stock_dates = dates_by_stock.setdefault(stock_id, set())
            if (
                trade_date in stock_dates
                or len(stock_dates) >= LIQUIDITY_LOOKBACK_SESSIONS
            ):
                continue
            stock_dates.add(trade_date)
            values_by_stock.setdefault(stock_id, []).append(
                Decimal(trading_value)
            )
        liquidity_rows = [
            (stock_id, Decimal(median(values)), len(values))
            for stock_id, values in values_by_stock.items()
            if len(values) >= LIQUIDITY_MINIMUM_SESSIONS
        ]
        liquidity_rows.sort(key=lambda item: item[1], reverse=True)
        universe_count = len(liquidity_rows)
        statistics: dict[int, tuple[int, Decimal, int, Decimal]] = {}
        for rank, (stock_id, median_value, sessions) in enumerate(
            liquidity_rows, start=1
        ):
            percentile = (
                Decimal(100)
                if universe_count <= 1
                else (
                    Decimal(universe_count - rank)
                    / Decimal(universe_count - 1)
                    * Decimal(100)
                ).quantize(Decimal("0.001"))
            )
            statistics[stock_id] = (rank, median_value, sessions, percentile)
        return statistics, universe_count

    @staticmethod
    def _financial_trends(
        session,
        stock_ids: list[int],
        *,
        basis_date: date,
    ) -> dict[int, _FinancialTrend]:
        report_order = case(
            (FinancialStatement.report_code == "11011", 4),
            (FinancialStatement.report_code == "11014", 3),
            (FinancialStatement.report_code == "11012", 2),
            (FinancialStatement.report_code == "11013", 1),
            else_=0,
        )
        rows = session.execute(
            select(FinancialStatement, FinancialAccount)
            .join(
                FinancialAccount,
                FinancialAccount.statement_id == FinancialStatement.id,
            )
            .where(
                FinancialStatement.stock_id.in_(stock_ids),
                FinancialStatement.filing_date <= basis_date,
                FinancialStatement.data_state == DataState.AVAILABLE.value,
                FinancialAccount.canonical_metric_code.in_(
                    (
                        "REVENUE",
                        "OPERATING_PROFIT",
                        "PARENT_OWNERS_NET_INCOME",
                        "NET_INCOME",
                    )
                ),
            )
            .order_by(
                FinancialStatement.stock_id,
                FinancialStatement.business_year.desc(),
                report_order.desc(),
                case((FinancialStatement.fs_div == "CFS", 0), else_=1),
                case(
                    (FinancialStatement.statement_kind.in_(("CIS", "IS")), 0),
                    else_=1,
                ),
                FinancialStatement.id.desc(),
            )
        ).all()
        selected_statement: dict[int, tuple[int, date]] = {}
        values: dict[int, dict[str, tuple[Decimal | None, Decimal | None]]] = {}
        for statement, account in rows:
            period_end = statement.period_end
            if period_end is None:
                month, day = {
                    "11013": (3, 31),
                    "11012": (6, 30),
                    "11014": (9, 30),
                    "11011": (12, 31),
                }[statement.report_code]
                period_end = date(statement.business_year, month, day)
            if period_end > basis_date:
                continue
            chosen = selected_statement.get(statement.stock_id)
            if chosen is None:
                selected_statement[statement.stock_id] = (statement.id, period_end)
            elif chosen[0] != statement.id:
                continue
            code = account.canonical_metric_code
            if code is None:
                continue
            current = (
                account.current_cumulative_amount
                if account.current_cumulative_amount is not None
                else account.current_amount
            )
            prior = (
                account.prior_cumulative_amount
                if account.prior_cumulative_amount is not None
                else account.prior_amount
            )
            stock_values = values.setdefault(statement.stock_id, {})
            stock_values.setdefault(code, (current, prior))

        trends: dict[int, _FinancialTrend] = {}
        for stock_id, (_, period_end) in selected_statement.items():
            stock_values = values.get(stock_id, {})
            revenue = stock_values.get("REVENUE", (None, None))
            operating = stock_values.get("OPERATING_PROFIT", (None, None))
            income = stock_values.get(
                "PARENT_OWNERS_NET_INCOME",
                stock_values.get("NET_INCOME", (None, None)),
            )
            comparable_pairs = (revenue, operating, income)
            if not any(current is not None and prior is not None for current, prior in comparable_pairs):
                continue
            trends[stock_id] = _FinancialTrend(
                period_end=period_end,
                revenue=revenue[0],
                prior_revenue=revenue[1],
                operating_profit=operating[0],
                prior_operating_profit=operating[1],
                net_income=income[0],
                prior_net_income=income[1],
            )
        return trends

    def close(self) -> None:
        self._engine.dispose()
