from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

import altair as alt
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.models.events import EarningsEstimateView, Phase5Snapshot
from app.models.financial import DividendView, StockAnalysisSnapshot
from app.models.market_analysis import IndexPoint
from app.models.metadata import DataState
from app.models.price import LatestDailyPrice
from app.models.recommendation import RecommendationDecision
from app.models.scoring import FilterState, Phase2Result
from app.models.status import ConnectionState
from app.models.stock import (
    ListingStatus,
    ProductType,
    ShareClass,
    StockQualityState,
    StockSearchResult,
)
from app.services.connection_status import get_connection_statuses
from app.services.entry_readiness_service import (
    EntryReadiness,
    EntryReadinessService,
)
from app.services.event_service import EventService
from app.services.index_service import IndexService
from app.services.market_status_service import MarketStatusService
from app.services.phase2_service import Phase2ScoringService
from app.services.price_service import CurrentStockQuote, PriceService
from app.services.stock_analysis_service import StockAnalysisService
from app.services.universe_service import UniverseService
from app.services.valuation_data_service import (
    ValuationDataService,
    ValuationReference,
)
from app.utils.dates import now_kst
from app.utils.technical_indicators import AdjustedPricePoint

_PRODUCT_LABELS = {
    ProductType.STOCK: "주식",
    ProductType.ETF: "ETF",
    ProductType.ETN: "ETN",
    ProductType.ELW: "ELW",
    ProductType.SPAC: "스팩",
    ProductType.REIT: "리츠",
    ProductType.SUBSCRIPTION_WARRANT: "신주인수권증권",
    ProductType.SUBSCRIPTION_RIGHT: "신주인수권증서",
    ProductType.OTHER_OFFICIAL: "기타 공식 상품구분",
    ProductType.UNKNOWN: "확인 불가",
}
_SHARE_CLASS_LABELS = {
    ShareClass.COMMON: "보통주",
    ShareClass.PREFERRED: "우선주",
    ShareClass.OTHER: "기타",
    ShareClass.UNKNOWN: "확인 불가",
}
_LISTING_LABELS = {
    ListingStatus.LISTED: "상장",
    ListingStatus.DELISTED: "상장폐지",
    ListingStatus.UNKNOWN: "확인 불가",
}
_QUALITY_LABELS = {
    StockQualityState.VALID: "정상",
    StockQualityState.REVIEW_REQUIRED: "수동 검토 필요",
    StockQualityState.MISSING_DART_CODE: "OpenDART 매핑 누락",
    StockQualityState.CONFLICT: "데이터 충돌",
}
_DATA_STATE_LABELS = {
    DataState.AVAILABLE: "확인됨",
    DataState.NOT_CONFIGURED: "키 미설정",
    DataState.NOT_VERIFIED: "연결 미검증",
    DataState.FETCH_FAILED: "수집 실패",
    DataState.STALE: "최신 확인 불가",
    DataState.MISSING: "매핑 누락",
    DataState.CONFLICT: "데이터 충돌",
    DataState.UNSUPPORTED: "지원 보류",
}
_DIVIDEND_PERIOD_LABELS = {
    "CASH_DPS": "연간 누적",
    "CASH_DPS_ANNUAL": "연간 누적",
    "CASH_DPS_H1": "반기 누적",
    "CASH_DPS_Q1": "1분기 누적",
    "CASH_DPS_Q3": "3분기 누적",
}
_DIVIDEND_PERIOD_RANK = {
    "CASH_DPS_Q1": 1,
    "CASH_DPS_H1": 2,
    "CASH_DPS_Q3": 3,
    "CASH_DPS": 4,
    "CASH_DPS_ANNUAL": 4,
}
_FINANCIAL_COMPARISON_METRICS = (
    ("REVENUE", "매출액"),
    ("OPERATING_PROFIT", "영업이익"),
    ("PARENT_OWNERS_NET_INCOME", "지배주주 순이익"),
    ("OPERATING_CASH_FLOW", "영업활동현금흐름"),
    ("ASSETS", "자산총계"),
    ("LIABILITIES", "부채총계"),
    ("PARENT_OWNERS_EQUITY", "지배주주지분"),
    ("FINANCE_COSTS", "금융비용"),
)


def _format_timestamp(value: datetime | None) -> str:
    if value is None:
        return "확인 불가"
    return value.strftime("%Y-%m-%d %H:%M:%S KST")


def _format_date(value: date | None) -> str:
    return value.isoformat() if value is not None else "확인 불가"


def _format_price(value: LatestDailyPrice | None) -> str:
    if value is None:
        return "가격 데이터 연결 필요"
    if value.currency == "KRW":
        return f"{value.close_price:,.0f}원"
    return f"{value.close_price:,.0f} (단위 미검증)"


def _format_value(value: object, unit: str | None = None) -> str:
    if value is None:
        return "확인 불가"
    suffix = f" {unit}" if unit else ""
    return f"{value:,}{suffix}"


def _dividend_frequency(dividends: tuple[DividendView, ...]) -> str:
    positive = [item for item in dividends if item.dps is not None and item.dps > 0]
    if any(item.dividend_type == "CASH_DPS_Q1" for item in positive):
        return "분기배당 이력 확인"
    if any(item.dividend_type in {"CASH_DPS_H1", "CASH_DPS_Q3"} for item in positive):
        return "중간배당 이력 확인"
    if any(item.dividend_type in {"CASH_DPS", "CASH_DPS_ANNUAL"} for item in positive):
        return "연배당만 확인"
    return "확인 불가"


def _format_dividend_yield(
    dps: Decimal | None,
    latest_price: LatestDailyPrice | None,
) -> str:
    if (
        dps is None
        or latest_price is None
        or latest_price.close_price <= 0
        or latest_price.currency != "KRW"
    ):
        return "확인 불가"
    dividend_yield = dps / latest_price.close_price * Decimal(100)
    return f"{dividend_yield.quantize(Decimal('0.01'))}%"


def _financial_chart_rows(
    values_by_year: dict[int, Decimal],
    mode: str,
) -> tuple[list[dict[str, object]], str]:
    ordered = sorted(values_by_year.items())
    if mode == "첫해=100 변화지수":
        baseline = ordered[0][1]
        if baseline <= 0:
            mode = "실제 금액(억원)"
        else:
            return (
                [
                    {
                        "사업연도": str(year),
                        "값": float(
                            (value / baseline * Decimal(100)).quantize(Decimal("0.01"))
                        ),
                    }
                    for year, value in ordered
                ],
                "변화지수 (첫해=100)",
            )
    if mode == "전년 대비 증감률(%)":
        rows: list[dict[str, object]] = []
        for (previous_year, previous), (year, value) in pairwise(ordered):
            if previous == 0:
                continue
            rows.append(
                {
                    "사업연도": f"{previous_year}→{year}",
                    "값": float(
                        ((value / previous - Decimal(1)) * Decimal(100)).quantize(
                            Decimal("0.01")
                        )
                    ),
                }
            )
        return rows, "전년 대비 증감률 (%)"
    return (
        [
            {
                "사업연도": str(year),
                "값": float((value / Decimal(100_000_000)).quantize(Decimal("0.01"))),
            }
            for year, value in ordered
        ],
        "금액 (억원)",
    )


def _stock_chart_rows(
    history: list[AdjustedPricePoint],
    *,
    visible_days: int,
) -> list[dict[str, object]]:
    ordered = sorted(history, key=lambda item: item.trade_date)
    closes: list[Decimal] = []
    rows: list[dict[str, object]] = []
    for item in ordered:
        closes.append(item.close)
        moving_averages: dict[int, float | None] = {}
        for period in (5, 20, 60, 120):
            moving_averages[period] = (
                float(sum(closes[-period:], Decimal(0)) / Decimal(period))
                if len(closes) >= period
                else None
            )
        open_price = item.open if item.open is not None else item.close
        rows.append(
            {
                "날짜": item.trade_date.isoformat(),
                "시가": float(open_price),
                "고가": float(item.high),
                "저가": float(item.low),
                "종가": float(item.close),
                "거래량": float(item.volume or Decimal(0)),
                "등락": "상승" if item.close >= open_price else "하락",
                "MA5": moving_averages[5],
                "MA20": moving_averages[20],
                "MA60": moving_averages[60],
                "MA120": moving_averages[120],
            }
        )
    return rows[-visible_days:]


@st.cache_data(ttl=300, show_spinner=False)
def _load_current_quote(
    _settings: Settings,
    symbol: str,
) -> CurrentStockQuote | None:
    service = PriceService(_settings)
    try:
        return asyncio.run(service.current_quote_for_symbol(symbol))
    finally:
        service.close()


def _latest_financial_value(
    snapshot: StockAnalysisSnapshot,
    metric_code: str,
) -> tuple[int, Decimal] | None:
    candidates = [
        item
        for item in snapshot.financial_history
        if item.metric_code == metric_code
        and item.value is not None
        and item.currency == "KRW"
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda item: item.business_year)
    assert latest.value is not None
    return latest.business_year, latest.value


def _stock_detail_needs_refresh(
    snapshot: StockAnalysisSnapshot | None,
    price_history: Sequence[AdjustedPricePoint],
    *,
    as_of_date: date | None = None,
) -> bool:
    financial_needed, price_needed = _stock_detail_refresh_needs(
        snapshot,
        price_history,
        as_of_date=as_of_date or now_kst().date(),
    )
    return financial_needed or price_needed


def _stock_detail_refresh_needs(
    snapshot: StockAnalysisSnapshot | None,
    price_history: Sequence[AdjustedPricePoint],
    *,
    as_of_date: date,
) -> tuple[bool, bool]:
    financial_years = {
        item.business_year
        for item in (snapshot.financial_history if snapshot is not None else ())
        if item.value is not None
    }
    financial_needed = snapshot is None or len(financial_years) < 3
    latest_price_date = max(
        (item.trade_date for item in price_history),
        default=None,
    )
    price_needed = (
        len(price_history) < 126
        or latest_price_date is None
        or latest_price_date < as_of_date - timedelta(days=7)
    )
    return financial_needed, price_needed


def _render_business_summary(
    stock: StockSearchResult,
    snapshot: StockAnalysisSnapshot,
    current_quote: CurrentStockQuote | None,
) -> None:
    st.subheader("사업·실적 요약")
    industry = current_quote.industry_name if current_quote is not None else None
    revenue = _latest_financial_value(snapshot, "REVENUE")
    operating_profit = _latest_financial_value(
        snapshot,
        "OPERATING_PROFIT",
    )
    net_income = _latest_financial_value(snapshot, "NET_INCOME")
    operating_cash_flow = _latest_financial_value(
        snapshot,
        "OPERATING_CASH_FLOW",
    )
    liabilities = _latest_financial_value(snapshot, "LIABILITIES")
    equity = _latest_financial_value(snapshot, "EQUITY")
    summary_parts = [
        (
            f"{stock.market_name or 'KOSPI'}에 상장된 "
            f"{stock.official_product_name or _PRODUCT_LABELS[stock.product_type]}입니다."
        )
    ]
    if industry:
        summary_parts.append(f"KIS 공식 업종 분류는 ‘{industry}’입니다.")
    if revenue is not None:
        summary_parts.append(
            f"{revenue[0]}년 매출은 {revenue[1] / Decimal(100_000_000):,.0f}억원입니다."
        )
    if operating_profit is not None:
        summary_parts.append(
            f"{operating_profit[0]}년 영업이익은 "
            f"{operating_profit[1] / Decimal(100_000_000):,.0f}억원입니다."
        )
    st.write(" ".join(summary_parts))
    revenue_history = sorted(
        (
            (item.business_year, item.value)
            for item in snapshot.financial_history
            if item.metric_code == "REVENUE" and item.value is not None
        ),
        reverse=True,
    )
    revenue_growth = None
    if (
        len(revenue_history) >= 2
        and revenue_history[1][1] is not None
        and revenue_history[1][1] != 0
    ):
        revenue_growth = (revenue_history[0][1] / revenue_history[1][1] - 1) * Decimal(
            100
        )
    metric_columns = st.columns(4)
    metric_items = (
        ("매출", revenue),
        ("영업이익", operating_profit),
        ("순이익", net_income),
        ("영업현금흐름", operating_cash_flow),
    )
    for column, (label, item) in zip(
        metric_columns,
        metric_items,
        strict=True,
    ):
        column.metric(
            label,
            (
                f"{item[1] / Decimal(100_000_000):,.0f}억원"
                if item is not None
                else "자료 없음"
            ),
            f"{item[0]}년" if item is not None else None,
            delta_color="off",
        )
    if liabilities is not None and equity is not None and equity[1] > 0:
        debt_ratio = liabilities[1] / equity[1] * Decimal(100)
        st.caption(
            f"{max(liabilities[0], equity[0])}년 부채비율 "
            f"{debt_ratio:,.1f}% · 연결 재무제표 기준"
        )
    operating_margin = (
        operating_profit[1] / revenue[1] * Decimal(100)
        if revenue is not None
        and operating_profit is not None
        and revenue[0] == operating_profit[0]
        and revenue[1] != 0
        else None
    )
    net_margin = (
        net_income[1] / revenue[1] * Decimal(100)
        if revenue is not None
        and net_income is not None
        and revenue[0] == net_income[0]
        and revenue[1] != 0
        else None
    )
    performance_notes = []
    if revenue_growth is not None:
        performance_notes.append(f"매출 전년 대비 {revenue_growth:+.1f}%")
    if operating_margin is not None:
        performance_notes.append(f"영업이익률 {operating_margin:.1f}%")
    if net_margin is not None:
        performance_notes.append(f"순이익률 {net_margin:.1f}%")
    if performance_notes:
        st.info("실적 핵심 · " + " · ".join(performance_notes))
    st.caption(
        "사업 설명은 확인된 시장·업종·재무 구조만 요약합니다. "
        "공식 사업부문 매출 데이터가 없으면 매출비중을 임의 생성하지 않습니다."
    )


def _render_annual_price_range(
    history: list[AdjustedPricePoint],
    current_quote: CurrentStockQuote | None,
) -> None:
    recent = sorted(history, key=lambda item: item.trade_date)[-252:]
    if not recent:
        return
    low = min(item.low for item in recent)
    high = max(item.high for item in recent)
    current = current_quote.price if current_quote is not None else recent[-1].close
    span = high - low
    position = (
        max(Decimal(0), min(Decimal(100), (current - low) / span * 100))
        if span > 0
        else Decimal(50)
    )
    st.subheader("연간 가격 위치")
    st.progress(float(position / Decimal(100)))
    low_column, current_column, high_column = st.columns(3)
    low_column.metric(
        "52주 최저",
        f"{low:,.0f}원",
        f"현재가 대비 {(current / low - 1) * 100:+.1f}%",
        delta_color="off",
    )
    current_column.metric("현재 위치", f"{position:.0f}%")
    high_column.metric(
        "52주 최고",
        f"{high:,.0f}원",
        f"현재가 대비 {(current / high - 1) * 100:+.1f}%",
        delta_color="off",
    )


def _forward_per_from_estimates(
    current_price: Decimal,
    estimates: Sequence[EarningsEstimateView],
    *,
    as_of_date: date,
) -> tuple[Decimal | None, str | None, int]:
    usable = [
        item
        for item in estimates
        if item.is_estimate
        and item.metric_code.upper()
        in {"EPS", "FORWARD_EPS", "CONSENSUS_EPS", "ESTIMATED_EPS"}
        and item.estimate_value is not None
        and item.estimate_value > 0
        and item.currency == "KRW"
        and len(item.fiscal_period) >= 4
        and item.fiscal_period[:4].isdigit()
        and int(item.fiscal_period[:4]) >= as_of_date.year
        and item.published_date <= as_of_date
    ]
    if not usable or current_price <= 0:
        return None, None, 0

    forward_year = min(int(item.fiscal_period[:4]) for item in usable)
    forward_periods = sorted(
        {
            item.fiscal_period
            for item in usable
            if int(item.fiscal_period[:4]) == forward_year
        }
    )
    forward_period = forward_periods[0]
    period_estimates = [item for item in usable if item.fiscal_period == forward_period]

    latest_by_broker: dict[str, EarningsEstimateView] = {}
    for item in period_estimates:
        broker_key = item.broker.strip().casefold() or item.provider.casefold()
        existing = latest_by_broker.get(broker_key)
        if existing is None or item.published_date > existing.published_date:
            latest_by_broker[broker_key] = item
    eps_values = sorted(
        item.estimate_value
        for item in latest_by_broker.values()
        if item.estimate_value is not None
    )
    if not eps_values:
        return None, forward_period, 0
    midpoint = len(eps_values) // 2
    median_eps = (
        eps_values[midpoint]
        if len(eps_values) % 2
        else (eps_values[midpoint - 1] + eps_values[midpoint]) / Decimal(2)
    )
    return current_price / median_eps, forward_period, len(eps_values)


def _render_valuation_overview(
    current_quote: CurrentStockQuote | None,
    phase2_result: Phase2Result | None,
    phase5_snapshot: Phase5Snapshot | None,
    valuation_reference: ValuationReference | None,
) -> None:
    comparison_values: dict[str, dict[str, Decimal]] = {
        "PER": {},
        "FPER": {},
        "PBR": {},
    }
    forward_sample_count = 0
    forward_period: str | None = None
    forward_per: Decimal | None = None
    forward_source: str | None = None
    if current_quote is not None and current_quote.forward_per is not None:
        forward_per = current_quote.forward_per
        forward_period = current_quote.forward_period
        forward_source = "KIS"
    elif current_quote is not None and phase5_snapshot is not None:
        forward_per, forward_period, forward_sample_count = _forward_per_from_estimates(
            current_quote.price,
            phase5_snapshot.earnings_estimates,
            as_of_date=now_kst().date(),
        )
        if forward_per is not None:
            forward_source = "CONSENSUS"
    if current_quote is not None:
        if current_quote.per is not None:
            comparison_values["PER"]["조회 종목"] = current_quote.per
        if forward_per is not None:
            comparison_values["FPER"]["조회 종목"] = forward_per
        if current_quote.pbr is not None:
            comparison_values["PBR"]["조회 종목"] = current_quote.pbr
    if phase2_result is not None:
        for item in phase2_result.valuation_comparisons:
            metric = item.metric_code.upper()
            if metric not in comparison_values:
                continue
            if (
                "조회 종목" not in comparison_values[metric]
                and item.current_value is not None
            ):
                comparison_values[metric]["조회 종목"] = item.current_value
            if item.industry_median is not None:
                comparison_values[metric]["동종업종 중앙값"] = item.industry_median
            if item.historical_median is not None:
                comparison_values[metric]["자체 역사 중앙값"] = item.historical_median
    if valuation_reference is not None:
        if (
            valuation_reference.per_median is not None
            and "동종업종 중앙값" not in comparison_values["PER"]
        ):
            comparison_values["PER"]["동종업종 참고값"] = valuation_reference.per_median
        if (
            valuation_reference.pbr_median is not None
            and "동종업종 중앙값" not in comparison_values["PBR"]
        ):
            comparison_values["PBR"]["동종업종 참고값"] = valuation_reference.pbr_median
    rows = [
        {
            "지표": metric,
            "비교대상": {
                "조회 종목": "종목",
                "동종업종 중앙값": "업종",
                "동종업종 참고값": "업종 참고",
                "자체 역사 중앙값": "과거",
            }.get(label, label),
            "값": float(value),
        }
        for metric, values in comparison_values.items()
        for label, value in values.items()
        if value >= 0
    ]
    st.subheader("가치평가")
    summary_columns = st.columns(3)
    summary_columns[0].metric(
        "PER",
        (
            f"{current_quote.per:.2f}배"
            if current_quote is not None and current_quote.per is not None
            else "자료 없음"
        ),
    )
    summary_columns[1].metric(
        "FPER",
        f"{forward_per:.2f}배" if forward_per is not None else "자료 없음",
    )
    summary_columns[2].metric(
        "PBR",
        (
            f"{current_quote.pbr:.2f}배"
            if current_quote is not None and current_quote.pbr is not None
            else "자료 없음"
        ),
    )
    if forward_per is None:
        st.caption(
            "FPER: 통화가 KRW로 검증된 증권사 예상 EPS가 없어 계산하지 "
            "않았습니다. KIS 현재가의 EPS는 과거 실적 기준이므로 사용하지 않습니다."
        )
    elif forward_source == "KIS":
        eps_text = (
            f"{current_quote.forward_eps:,.0f}원"
            if current_quote is not None and current_quote.forward_eps is not None
            else "제공값"
        )
        st.caption(
            f"FPER: KIS {forward_period} 종목추정실적 기준 · 예상 EPS {eps_text}"
        )
    else:
        st.caption(
            f"FPER: 현재가 ÷ {forward_period} 예상 EPS 중앙값 "
            f"(증권사 최신치 {forward_sample_count}건)"
        )
    metric_columns = st.columns(3)
    for column, metric in zip(
        metric_columns,
        ("PER", "FPER", "PBR"),
        strict=True,
    ):
        metric_rows = [row for row in rows if row["지표"] == metric]
        with column:
            st.markdown(
                f"<div style='text-align:center;font-size:1rem;"
                f"font-weight:700;margin-bottom:.35rem'>{metric}</div>",
                unsafe_allow_html=True,
            )
            if not metric_rows:
                reason = "예상 EPS 미제공" if metric == "FPER" else "비교 데이터 미제공"
                st.markdown(
                    "<div style='height:285px;display:flex;"
                    "flex-direction:column;align-items:center;"
                    "justify-content:center;border:1px solid "
                    "rgba(148,163,184,.14);border-radius:8px'>"
                    "<div style='font-size:1.05rem;font-weight:700;"
                    "color:#c8d2df'>자료 없음</div>"
                    f"<div style='font-size:.78rem;color:#8c98a8;"
                    f"margin-top:.35rem'>{reason}</div></div>",
                    unsafe_allow_html=True,
                )
                continue
            base = alt.Chart(alt.Data(values=metric_rows)).encode(
                x=alt.X(
                    "비교대상:N",
                    title=None,
                    sort=["종목", "업종", "업종 참고", "과거"],
                    axis=alt.Axis(
                        labelAngle=0,
                        labelFontSize=13,
                        labelPadding=10,
                        ticks=False,
                        domain=False,
                    ),
                ),
                y=alt.Y(
                    "값:Q",
                    title=None,
                    scale=alt.Scale(zero=True, nice=True),
                    axis=alt.Axis(
                        labelFontSize=11,
                        grid=True,
                        gridOpacity=0.16,
                        ticks=False,
                        domain=False,
                    ),
                ),
                color=alt.Color(
                    "비교대상:N",
                    title=None,
                    scale=alt.Scale(
                        domain=["종목", "업종", "업종 참고", "과거"],
                        range=["#f28b23", "#9aa3ad", "#9aa3ad", "#5b7fc7"],
                    ),
                    legend=None,
                ),
                tooltip=[
                    "비교대상:N",
                    alt.Tooltip("값:Q", format=",.2f", title="배수"),
                ],
            )
            bars = base.mark_bar(
                size=42,
                cornerRadiusTopLeft=6,
                cornerRadiusTopRight=6,
            )
            value_labels = base.mark_text(
                dy=-12,
                fontSize=12,
                fontWeight="bold",
            ).encode(text=alt.Text("값:Q", format=",.2f"))
            chart = (
                (bars + value_labels)
                .properties(height=285)
                .configure_view(strokeOpacity=0)
                .configure_axis(
                    labelColor="#c8d2df",
                    titleColor="#c8d2df",
                )
            )
            st.altair_chart(chart, width="stretch")
    if valuation_reference is not None:
        st.caption(
            f"업종 참고값: DART {valuation_reference.comparison_label} 분류와 "
            "KIS 최신 양수 배수를 사용한 중앙값 · "
            f"PER {valuation_reference.per_sample_count}개사 · "
            f"PBR {valuation_reference.pbr_sample_count}개사. "
            "표본이 적으면 추천 점수에는 사용하지 않고 화면 참고값으로만 표시합니다."
        )


def _period_return(
    points: Sequence[AdjustedPricePoint | IndexPoint],
    lookback: int,
) -> Decimal | None:
    if len(points) <= lookback:
        return None
    latest = points[-1].close
    previous = points[-lookback - 1].close
    if previous <= 0:
        return None
    return (latest / previous - 1) * Decimal(100)


def _render_period_returns(
    history: list[AdjustedPricePoint],
    index_history: list[IndexPoint],
) -> None:
    stock_points = sorted(history, key=lambda item: item.trade_date)
    index_points = sorted(index_history, key=lambda item: item.trade_date)
    periods = (("1개월", 21), ("2개월", 42), ("3개월", 63))
    rows: list[dict[str, object]] = []
    for label, lookback in periods:
        for series_name, points in (
            ("조회 종목", stock_points),
            ("코스피", index_points),
        ):
            value = _period_return(points, lookback)
            if value is not None:
                rows.append(
                    {
                        "기간": label,
                        "종목/벤치마크": series_name,
                        "수익률": float(value),
                    }
                )
    st.subheader("기간별 수익률")
    if not rows:
        st.info("기간별 수익률을 계산할 가격 이력이 부족합니다.")
        return
    chart = (
        alt.Chart(alt.Data(values=rows))
        .mark_bar(
            size=30,
            cornerRadiusTopLeft=5,
            cornerRadiusTopRight=5,
        )
        .encode(
            x=alt.X(
                "기간:N",
                sort=[item[0] for item in periods],
                title=None,
                axis=alt.Axis(
                    labelAngle=0,
                    labelOverlap=False,
                    labelPadding=8,
                ),
            ),
            y=alt.Y(
                "수익률:Q",
                title="수익률 (%)",
                axis=alt.Axis(gridOpacity=0.16, domain=False),
            ),
            xOffset="종목/벤치마크:N",
            color=alt.Color(
                "종목/벤치마크:N",
                title=None,
                scale=alt.Scale(
                    domain=["조회 종목", "코스피"],
                    range=["#f28b23", "#8b97a8"],
                ),
            ),
            tooltip=[
                "기간:N",
                "종목/벤치마크:N",
                alt.Tooltip("수익률:Q", format="+.2f"),
            ],
        )
        .properties(height=300)
        .configure_view(strokeOpacity=0)
        .configure_axis(labelColor="#c8d2df", titleColor="#c8d2df")
        .configure_legend(
            orient="top",
            direction="horizontal",
            labelColor="#c8d2df",
            title=None,
        )
    )
    st.altair_chart(chart, width="stretch")
    if stock_points and index_points:
        st.caption(
            f"조회 종목 {stock_points[-1].trade_date.isoformat()} · "
            f"코스피 {index_points[-1].trade_date.isoformat()} 확정 일봉 기준"
        )


def _render_investor_flows(snapshot: Phase5Snapshot | None) -> None:
    st.subheader("투자자별 순매수")
    if snapshot is None or not snapshot.investor_flows:
        st.info("저장된 투자자별 순매수 데이터가 없습니다.")
        return
    latest_date = max(item.trade_date for item in snapshot.investor_flows)
    labels = {
        "INDIVIDUAL": "개인",
        "FOREIGN": "외국인",
        "INSTITUTION": "기관계",
    }
    rows = [
        {
            "투자자": labels.get(item.investor_type, item.investor_type),
            "순매수": float(item.net_purchase_quantity),
            "방향": (
                "매수"
                if item.net_purchase_quantity is not None
                and item.net_purchase_quantity >= 0
                else "매도"
            ),
        }
        for item in snapshot.investor_flows
        if item.trade_date == latest_date and item.net_purchase_quantity is not None
    ]
    if not rows:
        st.info("최근 거래일의 순매수 수량을 확인할 수 없습니다.")
        return
    chart = (
        alt.Chart(alt.Data(values=rows))
        .mark_bar(
            size=44,
            cornerRadiusTopLeft=6,
            cornerRadiusTopRight=6,
        )
        .encode(
            x=alt.X(
                "투자자:N",
                title=None,
                sort=["개인", "외국인", "기관계"],
                axis=alt.Axis(
                    labelAngle=0,
                    labelOverlap=False,
                    labelPadding=8,
                ),
            ),
            y=alt.Y(
                "순매수:Q",
                title="순매수 수량 (주)",
                axis=alt.Axis(gridOpacity=0.16, domain=False),
            ),
            color=alt.Color(
                "방향:N",
                scale=alt.Scale(
                    domain=["매수", "매도"],
                    range=["#df4b57", "#3f7fca"],
                ),
                legend=None,
            ),
            tooltip=[
                "투자자:N",
                alt.Tooltip("순매수:Q", format="+,.0f"),
            ],
        )
        .properties(height=310)
        .configure_view(strokeOpacity=0)
        .configure_axis(labelColor="#c8d2df", titleColor="#c8d2df")
    )
    st.altair_chart(chart, width="stretch")
    st.caption(f"{latest_date.isoformat()} 기준 · 양수는 순매수, 음수는 순매도")


def _render_dividend_overview(
    snapshot: StockAnalysisSnapshot,
    history: list[AdjustedPricePoint],
    current_price: Decimal | None,
) -> None:
    st.subheader("배당")
    annual = sorted(
        (
            item
            for item in snapshot.dividends
            if item.dividend_type in {"CASH_DPS", "CASH_DPS_ANNUAL"}
            and item.dps is not None
            and item.dps > 0
        ),
        key=lambda item: item.business_year,
        reverse=True,
    )
    if not annual:
        st.info("확인된 연간 주당배당금이 없습니다.")
        return
    latest = annual[0]
    assert latest.dps is not None
    previous_year = now_kst().year - 1
    previous_year_prices = [
        item for item in history if item.trade_date.year == previous_year
    ]
    reference_price = (
        previous_year_prices[-1].close if previous_year_prices else current_price
    )
    hypothetical = None
    if reference_price is not None and reference_price > 0:
        shares = Decimal(1_000_000) // reference_price
        hypothetical = shares * latest.dps
    dividend_yield = (
        latest.dps / current_price * Decimal(100)
        if current_price is not None and current_price > 0
        else None
    )
    st.markdown(
        "#### "
        + (
            f"{previous_year}년 말 기준 100만원을 보유했다면 "
            f"연 {hypothetical:,.0f}원 배당"
            if hypothetical is not None
            else "100만원 보유 가정 배당액은 기준가격 부족으로 계산 불가"
        )
    )
    columns = st.columns(3)
    columns[0].metric("배당방식", _dividend_frequency(snapshot.dividends))
    columns[1].metric(
        f"{latest.business_year}년 1주당 배당금",
        f"{latest.dps:,.0f}원",
    )
    columns[2].metric(
        "현재가 기준 배당률",
        f"{dividend_yield:.2f}%" if dividend_yield is not None else "확인 불가",
    )
    st.caption(
        "100만원 가정은 전년도 마지막 저장 수정주가로 매수 가능한 정수 주식 수에 "
        "최신 확정 연간 DPS를 적용한 단순 비교값입니다."
    )


@st.fragment(run_every=300)
def _render_stock_price_panel(
    settings: Settings,
    stock: StockSearchResult,
    latest_price: LatestDailyPrice | None,
    history: list[AdjustedPricePoint],
    snapshot: StockAnalysisSnapshot,
    phase2_result: Phase2Result | None,
    phase5_snapshot: Phase5Snapshot | None,
    index_history: list[IndexPoint],
    valuation_reference: ValuationReference | None,
) -> None:
    st.divider()
    title_column, refresh_column = st.columns([4, 1])
    with title_column:
        st.caption(
            f"{stock.market_name or 'KOSPI'} · "
            f"{stock.official_product_name or _PRODUCT_LABELS[stock.product_type]} · "
            "5분 갱신 현재가"
        )
        st.markdown(f"## {stock.name} · {stock.symbol}")
    with refresh_column:
        refresh_quote = st.button(
            "현재가 갱신",
            width="stretch",
            key=f"refresh-current-quote-{stock.symbol}",
        )
    if refresh_quote:
        _load_current_quote.clear()
    current_quote = _load_current_quote(settings, stock.symbol)

    confirmed_history = sorted(history, key=lambda item: item.trade_date)
    ordered = list(confirmed_history)
    if current_quote is not None:
        quote_date = current_quote.as_of_at.date()
        quote_open = (
            current_quote.open_price
            if current_quote.open_price is not None and current_quote.open_price > 0
            else current_quote.price
        )
        quote_high = (
            current_quote.high_price
            if current_quote.high_price is not None and current_quote.high_price > 0
            else max(quote_open, current_quote.price)
        )
        quote_low = (
            current_quote.low_price
            if current_quote.low_price is not None and current_quote.low_price > 0
            else min(quote_open, current_quote.price)
        )
        ordered = [item for item in ordered if item.trade_date != quote_date]
        ordered.append(
            AdjustedPricePoint(
                trade_date=quote_date,
                open=quote_open,
                high=max(quote_high, quote_open, current_quote.price),
                low=min(quote_low, quote_open, current_quote.price),
                close=current_quote.price,
                volume=current_quote.volume,
                is_adjusted=False,
                adjustment_status="INTRADAY_PROVISIONAL",
                source_provider=current_quote.source_provider,
            )
        )
        ordered.sort(key=lambda item: item.trade_date)

    history_latest = ordered[-1] if ordered else None
    use_current_quote = current_quote is not None
    use_latest_price = (
        not use_current_quote
        and latest_price is not None
        and (
            history_latest is None
            or latest_price.trade_date >= history_latest.trade_date
        )
    )
    current = (
        current_quote.price
        if current_quote is not None
        else latest_price.close_price
        if use_latest_price and latest_price is not None
        else history_latest.close
        if history_latest is not None
        else None
    )
    previous = None
    if current_quote is not None and current_quote.previous_day_change is not None:
        previous = current_quote.price - current_quote.previous_day_change
    elif (
        use_latest_price
        and latest_price is not None
        and history_latest is not None
        and latest_price.trade_date > history_latest.trade_date
    ):
        previous = history_latest.close
    elif len(ordered) >= 2:
        previous = ordered[-2].close
    change = (
        current_quote.previous_day_change
        if current_quote is not None and current_quote.previous_day_change is not None
        else current - previous
        if current is not None and previous is not None
        else None
    )
    change_rate = (
        current_quote.change_rate
        if current_quote is not None and current_quote.change_rate is not None
        else change / previous * Decimal(100)
        if change is not None and previous is not None and previous > 0
        else None
    )
    delta = (
        f"{change:+,.0f}원 ({change_rate:+.2f}%)"
        if change is not None and change_rate is not None
        else None
    )

    price_columns = st.columns(4)
    price_columns[0].metric(
        "5분 갱신 현재가" if current_quote is not None else "최근 확정종가",
        f"{current:,.0f}원" if current is not None else "확인 불가",
        delta,
        delta_color="off",
    )
    price_columns[1].metric(
        "거래량",
        (
            f"{current_quote.volume:,.0f}주"
            if current_quote is not None and current_quote.volume is not None
            else f"{latest_price.volume:,.0f}주"
            if use_latest_price
            and latest_price is not None
            and latest_price.volume is not None
            else (
                f"{history_latest.volume:,.0f}주"
                if history_latest is not None and history_latest.volume is not None
                else "확인 불가"
            )
        ),
    )
    price_columns[2].metric(
        "RSI 14",
        (
            f"{snapshot.technical.rsi_14:.1f}"
            if snapshot.technical.rsi_14 is not None
            else "확인 불가"
        ),
    )
    price_columns[3].metric(
        "52주 고점 대비",
        (
            f"{snapshot.technical.drawdown_52_week * Decimal(100):.1f}%"
            if snapshot.technical.drawdown_52_week is not None
            else "확인 불가"
        ),
    )
    if current_quote is not None:
        st.caption(
            f"조회시각 {current_quote.as_of_at.strftime('%Y-%m-%d %H:%M:%S KST')} · "
            "한국투자증권 현재가 · 5분 자동 갱신 · 장중 잠정값"
        )
    elif use_latest_price and latest_price is not None:
        st.caption(
            f"가격 기준일 {latest_price.trade_date.isoformat()} · "
            f"{latest_price.source_provider} 확정 종가"
        )
    elif history_latest is not None:
        st.caption(
            f"가격 기준일 {history_latest.trade_date.isoformat()} · "
            f"{history_latest.source_provider or '공식 제공처'} 확정 일봉"
        )

    if not ordered:
        st.warning(
            "검증된 수정주가 이력이 없어 일봉 차트를 표시할 수 없습니다. "
            "공식 데이터 새로고침을 실행하세요."
        )
        return

    period_label = st.radio(
        "차트 기간",
        options=("3개월", "6개월", "1년"),
        index=1,
        horizontal=True,
        key=f"stock-chart-period-{stock.symbol}",
    )
    visible_days = {"3개월": 65, "6개월": 130, "1년": 252}[period_label]
    rows = _stock_chart_rows(ordered, visible_days=visible_days)
    data = alt.Data(values=rows)
    base = alt.Chart(data).encode(
        x=alt.X("날짜:T", title=None, axis=alt.Axis(format="%y.%m")),
    )
    color = alt.condition(
        "datum['등락'] === '상승'",
        alt.value("#df4b57"),
        alt.value("#3f7fca"),
    )
    wicks = base.mark_rule().encode(
        y=alt.Y(
            "저가:Q",
            title="가격 (원)",
            scale=alt.Scale(zero=False, padding=12),
        ),
        y2="고가:Q",
        color=color,
    )
    candles = base.mark_bar(size=5).encode(
        y=alt.Y("시가:Q"),
        y2="종가:Q",
        color=color,
        tooltip=[
            alt.Tooltip("날짜:T", format="%Y-%m-%d"),
            alt.Tooltip("시가:Q", format=",.0f"),
            alt.Tooltip("고가:Q", format=",.0f"),
            alt.Tooltip("저가:Q", format=",.0f"),
            alt.Tooltip("종가:Q", format=",.0f"),
            alt.Tooltip("거래량:Q", format=",.0f"),
        ],
    )
    moving_averages = (
        base.transform_fold(
            ["MA5", "MA20", "MA60", "MA120"],
            as_=["이동평균", "이동평균값"],
        )
        .transform_filter("isValid(datum['이동평균값'])")
        .mark_line(strokeWidth=1.7)
        .encode(
            y=alt.Y("이동평균값:Q"),
            color=alt.Color(
                "이동평균:N",
                title=None,
                scale=alt.Scale(
                    domain=["MA5", "MA20", "MA60", "MA120"],
                    range=["#e5a11a", "#3f7fca", "#64864b", "#39a58c"],
                ),
                legend=alt.Legend(orient="top"),
            ),
        )
    )
    price_chart = (
        (wicks + candles + moving_averages)
        .properties(height=460)
        .resolve_scale(color="independent")
    )
    st.altair_chart(price_chart, width="stretch")

    volume_chart = (
        alt.Chart(data)
        .mark_bar()
        .encode(
            x=alt.X("날짜:T", title=None, axis=alt.Axis(format="%y.%m")),
            y=alt.Y("거래량:Q", title="거래량", axis=alt.Axis(format="~s")),
            color=color,
            tooltip=[
                alt.Tooltip("날짜:T", format="%Y-%m-%d"),
                alt.Tooltip("거래량:Q", format=",.0f"),
            ],
        )
        .properties(height=130)
    )
    st.altair_chart(volume_chart, width="stretch")
    st.caption(
        "빨강은 상승일, 파랑은 하락일입니다. 이동평균선은 "
        "5일·20일·60일·120일 기준입니다. 당일 현재가는 잠정 일봉으로 "
        "차트 마지막 날짜에 반영되며, 다음 KRX 확정 일봉으로 대체됩니다."
    )
    st.divider()
    _render_business_summary(stock, snapshot, current_quote)
    st.divider()
    _render_annual_price_range(ordered, current_quote)
    st.divider()
    _render_valuation_overview(
        current_quote,
        phase2_result,
        phase5_snapshot,
        valuation_reference,
    )
    st.divider()
    _render_period_returns(ordered, index_history)
    st.divider()
    _render_investor_flows(phase5_snapshot)
    st.divider()
    _render_dividend_overview(snapshot, ordered, current)


def _failed_filter_names(result: Phase2Result) -> list[str]:
    return [
        item.name
        for item in result.filters
        if item.is_blocking and item.state.value == "FAIL"
    ]


def _return_to_recommendations() -> None:
    st.session_state["main_menu"] = "추천종목"
    st.session_state.pop("stock_detail_origin", None)
    st.session_state.pop("stock_detail_recommendation", None)


def _recommendation_evidence_rows(
    item: RecommendationDecision,
    key: str,
) -> tuple[dict[str, object], ...]:
    raw_rows = item.raw_metrics.get(key)
    if not isinstance(raw_rows, (list, tuple)):
        return ()
    return tuple(row for row in raw_rows if isinstance(row, dict))


def _render_recommendation_event_context(item: RecommendationDecision) -> None:
    evidences = _recommendation_evidence_rows(item, "detail_event_evidences")
    news_rows = _recommendation_evidence_rows(item, "detail_news_evidences")
    has_event_payload = "detail_event_evidences" in item.raw_metrics
    if not has_event_payload:
        st.info(
            "이 상세 화면은 변경 전 추천 선택값입니다. 추천 목록으로 돌아가 종목을 "
            "다시 선택하면 뉴스·공시 호재·악재가 함께 표시됩니다."
        )
        return

    positive = tuple(
        row for row in evidences if row.get("sentiment") == "POSITIVE"
    )
    negative = tuple(
        row for row in evidences if row.get("sentiment") == "NEGATIVE"
    )
    news_count = int(str(item.raw_metrics.get("detail_news_article_count") or 0))
    disclosure_count = int(
        str(item.raw_metrics.get("detail_disclosure_count") or 0)
    )
    st.markdown("#### 뉴스·공시 호재·악재")
    st.caption(
        f"선택 당시 최근 90일 네이버 뉴스 {news_count}건 · "
        f"공식 공시 {disclosure_count}건 기준"
    )
    good_column, bad_column = st.columns(2)
    with good_column:
        st.markdown(f"##### 호재 {len(positive)}건")
        if positive:
            for row in positive:
                source = "네이버 뉴스" if row.get("source_kind") == "NEWS" else "공시"
                st.markdown(
                    f"- {row.get('published_date')} · {source} · {row.get('title')}"
                )
        else:
            st.caption("확인된 호재 신호가 없습니다.")
    with bad_column:
        st.markdown(f"##### 악재 {len(negative)}건")
        if negative:
            for row in negative:
                source = "네이버 뉴스" if row.get("source_kind") == "NEWS" else "공시"
                st.markdown(
                    f"- {row.get('published_date')} · {source} · {row.get('title')}"
                )
        else:
            st.caption("확인된 악재 신호가 없습니다.")

    with st.expander("주요 네이버 뉴스 요약·판정 근거"):
        if news_rows:
            for index, row in enumerate(news_rows, start=1):
                sentiment = str(row.get("sentiment") or "UNCLASSIFIED")
                direction = (
                    "호재"
                    if sentiment == "POSITIVE"
                    else "악재"
                    if sentiment == "NEGATIVE"
                    else "중립·미분류"
                )
                st.markdown(
                    f"**{row.get('published_date')} · {direction} · "
                    f"{row.get('title')}**"
                )
                st.write(str(row.get("summary") or "제공 요약 없음"))
                source_url = row.get("source_url")
                if isinstance(source_url, str) and source_url:
                    st.link_button(
                        "기사 원문 보기",
                        source_url,
                        key=f"detail-news-{item.symbol}-{index}",
                        width="content",
                    )
        else:
            st.caption("선택 당시 저장된 네이버 뉴스 요약이 없습니다.")


def _render_recommendation_context(
    item: RecommendationDecision,
    *,
    entry_threshold: Decimal,
) -> None:
    detail_score_label = str(
        item.raw_metrics.get("detail_score_label") or "저평가 매력"
    )
    detail_score_raw = item.raw_metrics.get("detail_score")
    detail_score = (
        Decimal(str(detail_score_raw))
        if detail_score_raw is not None
        else item.investment_score
    )
    detail_status = item.raw_metrics.get("detail_status_label")
    st.subheader("추천 결과 상세")
    st.caption(
        "추천 목록에서 선택한 시점의 판정과 계산 근거입니다. "
        "아래 차트·재무·배당 자료와 함께 확인하세요."
    )
    with st.container(border=True):
        metrics = st.columns(5)
        metrics[0].metric("추천 판정", item.category_label)
        metrics[1].metric(
            detail_score_label,
            (
                f"{detail_score}/100"
                if detail_score is not None
                else "계산 불가"
            ),
        )
        metrics[2].metric(
            f"진입준비도 ({entry_threshold}점↑ 권장)",
            (
                f"{item.entry_score}/100"
                if item.entry_score is not None
                else "계산 불가"
            ),
        )
        metrics[3].metric(
            "데이터 신뢰도",
            (
                f"{item.data_confidence}/100"
                if item.data_confidence is not None
                else "계산 불가"
            ),
        )
        metrics[4].metric(
            "목표비중",
            (
                f"{item.target_weight * Decimal(100):.2f}%"
                if item.target_weight is not None
                else "비선정"
            ),
        )
        if detail_status:
            st.caption(f"선택 당시 세부 판정: {detail_status}")
        if detail_score_raw is not None and item.investment_score is not None:
            st.caption(
                "카테고리별 독립 판정입니다. "
                f"참고용 1번 재무추천 저평가 매력은 {item.investment_score}/100입니다. "
                "이 점수가 낮다는 사실만으로 강제 투자배제된 것은 아닙니다."
            )

        positive_column, risk_column = st.columns(2)
        with positive_column:
            st.markdown("#### 추천 근거")
            for reason in item.positive_reasons or ("확인된 긍정 근거가 없습니다.",):
                st.write(f"- {reason}")
        with risk_column:
            st.markdown("#### 위험·제외 근거")
            reasons = (*item.risk_reasons, *item.exclusion_reasons)
            for reason in reasons or ("추가 위험 근거가 없습니다.",):
                st.write(f"- {reason}")

        _render_recommendation_event_context(item)

        if item.missing_data:
            st.warning("추가 확인 데이터: " + ", ".join(item.missing_data))

        with st.expander("추천 점수 구성요소·강제필터 상세"):
            components = item.raw_metrics.get("score_components", [])
            if components:
                st.markdown("##### 점수 구성요소")
                st.dataframe(components, width="stretch")
            st.markdown("##### 강제필터")
            st.dataframe(list(item.filter_results), width="stretch")
            st.caption(
                f"점수 범위 {item.score_scope} · 진입점수 범위 {item.entry_score_scope}"
            )


def _format_phase2_score(value: object, result: Phase2Result) -> str:
    if value is not None:
        return f"{value}/100"
    failed_filters = _failed_filter_names(result)
    if failed_filters:
        return "강제필터 미통과로 미산출 (" + ", ".join(failed_filters) + ")"
    if result.missing_core_data:
        return "핵심 데이터 부족으로 미산출"
    return "점수 미산출"


def _format_phase2_decision(result: Phase2Result | None) -> str:
    if result is None:
        return "계산 결과 없음"
    if result.recommendation_computable:
        return "점수 계산 가능"
    failed_filters = _failed_filter_names(result)
    if failed_filters:
        return "강제필터 미통과: " + ", ".join(failed_filters)
    review_filters = [
        item.name
        for item in result.filters
        if item.is_blocking and item.state == FilterState.REVIEW_REQUIRED
    ]
    if review_filters:
        return "수동 검토 필요: " + ", ".join(review_filters)
    if result.missing_core_data:
        return "데이터 부족으로 계산 불가"
    return "추천 계산 불가"


def _format_going_concern(
    status: str,
    risk: bool | None,
) -> str:
    if status != "VERIFIED" or risk is None:
        return "확인 불가"
    return "중대한 불확실성 확인" if risk else "중대한 불확실성 없음"


def _render_phase2_score(
    result: Phase2Result | None,
    entry_readiness: EntryReadiness | None,
) -> None:
    if result is None:
        st.warning(
            "Phase 2 강제필터·점수 계산 결과가 없습니다. "
            "저장된 공식 데이터를 확인한 뒤 점수 계산 명령을 실행하세요."
        )
        return
    st.write(
        "기본 투자매력:",
        _format_phase2_score(result.investment_score, result),
    )
    st.write(
        "개별 종목 진입 구성요소:",
        _format_phase2_score(result.individual_entry_score, result),
    )
    if entry_readiness is None:
        st.write("전체 진입준비:", "Phase 3 시장 분석 결과 없음")
    elif entry_readiness.score is None:
        if result.individual_entry_score is None:
            st.write(
                "전체 진입준비:",
                "Phase 2 개별 진입점수 미산출로 계산 보류",
            )
        else:
            st.write("전체 진입준비:", "Phase 3 핵심 입력 부족으로 계산 보류")
        if (
            result.individual_entry_score is not None
            and entry_readiness.missing_core_data
        ):
            st.caption(
                "Phase 3 누락 데이터: " + ", ".join(entry_readiness.missing_core_data)
            )
    else:
        st.write("전체 진입준비:", f"{entry_readiness.score}/100")
        st.caption(
            "시장 국면 "
            f"{entry_readiness.market_regime.value} · "
            f"Phase 3 기준시각 {_format_timestamp(entry_readiness.as_of_at)}"
        )
    st.write("데이터 신뢰도:", f"{result.data_confidence}/100")
    st.write(
        "추천 계산 가능 여부:",
        "가능" if result.recommendation_computable else "계산 불가",
    )
    st.write("점수 버전:", result.score_version)
    st.write("규칙 버전:", result.rule_version)
    st.caption(
        "현재 점수 범위는 Phase 2 배당·재무·밸류에이션 핵심 구성요소입니다. "
        "시장충격·뉴스·수급을 포함한 최종 추천은 생성하지 않습니다."
    )
    if result.missing_core_data:
        review_codes = {
            item.code
            for item in result.filters
            if item.state == FilterState.REVIEW_REQUIRED
        }
        missing_codes = [
            code for code in result.missing_core_data if code not in review_codes
        ]
        if missing_codes:
            st.error("누락된 핵심 데이터: " + ", ".join(missing_codes))
        if review_codes:
            review_reasons = [
                f"{item.name}: {item.reason}"
                for item in result.filters
                if item.state == FilterState.REVIEW_REQUIRED
            ]
            st.warning("수동 검토 필요 · " + " / ".join(review_reasons))
    st.info(result.explanation)
    st.subheader("강제필터")
    st.dataframe(
        [
            {
                "필터": item.name,
                "코드": item.code,
                "판정": item.state.value,
                "원시값": (
                    item.raw_value
                    if item.raw_value is not None
                    else item.raw_text or "확인 불가"
                ),
                "근거": item.reason,
                "출처": item.source_provider or "확인 불가",
                "기준일": _format_date(item.evidence_date),
            }
            for item in result.filters
        ],
        width="stretch",
        hide_index=True,
    )
    st.subheader("점수 계산근거")
    if not result.components:
        st.warning("강제필터 미통과로 점수 구성요소를 계산하지 않았습니다.")
    else:
        st.dataframe(
            [
                {
                    "점수": item.score_name,
                    "구성요소": item.code,
                    "상태": item.state.value,
                    "원시값": (
                        item.raw_value
                        if item.raw_value is not None
                        else item.raw_text or "확인 불가"
                    ),
                    "정규화값": item.normalized_value,
                    "가중치": item.weight,
                    "기여점": item.contribution,
                    "계산근거": item.explanation,
                    "구분": item.source_kind,
                }
                for item in result.components
            ],
            width="stretch",
            hide_index=True,
        )
    if result.valuation_comparisons:
        st.subheader("산업·자체 역사 밸류에이션")
        st.dataframe(
            [
                {
                    "지표": item.metric_code,
                    "상태": item.state.value,
                    "현재값": item.current_value,
                    "산업 중앙값": item.industry_median,
                    "자체 역사 중앙값": item.historical_median,
                    "산업 내 백분위": item.industry_percentile,
                    "자체 역사 백분위": item.historical_percentile,
                    "비교 수준": item.comparison_level or "비교 불가",
                    "표본 수": item.sample_size,
                    "근거": item.explanation,
                }
                for item in result.valuation_comparisons
            ],
            width="stretch",
            hide_index=True,
        )


def _render_analysis_tabs(
    snapshot: StockAnalysisSnapshot,
    phase2_result: Phase2Result | None,
    entry_readiness: EntryReadiness | None,
    latest_price: LatestDailyPrice | None,
) -> None:
    (
        summary_tab,
        score_tab,
        dividend_tab,
        finance_tab,
        audit_tab,
        technical_tab,
        source_tab,
    ) = st.tabs(
        [
            "요약",
            "강제필터·점수",
            "배당",
            "재무",
            "감사",
            "기술지표·진입시점",
            "공시·원자료",
        ]
    )
    with summary_tab:
        st.write(
            "재무 범위:",
            {
                "CFS": "연결재무제표",
                "OFS": "별도재무제표",
                "UNKNOWN": "확인 불가",
            }.get(snapshot.financial_scope.value, "확인 불가"),
        )
        st.write(
            "최근 감사의견:",
            (
                snapshot.latest_audit.opinion or "확인 불가"
                if snapshot.latest_audit is not None
                else "데이터 연결 필요"
            ),
        )
        st.write(
            "수정가격 확인:",
            (
                "확인됨"
                if snapshot.technical.state == DataState.AVAILABLE
                else "확인 불가"
            ),
        )
        st.write(
            "Phase 2 판정:",
            _format_phase2_decision(phase2_result),
        )

    with score_tab:
        _render_phase2_score(phase2_result, entry_readiness)

    with dividend_tab:
        if not snapshot.dividends:
            st.warning("OpenDART 최근 5개 사업연도 확정 DPS 데이터가 없습니다.")
        else:
            ordered_dividends = sorted(
                snapshot.dividends,
                key=lambda item: (
                    item.business_year,
                    _DIVIDEND_PERIOD_RANK.get(item.dividend_type or "", 0),
                ),
                reverse=True,
            )
            annual_dividends = [
                item
                for item in ordered_dividends
                if item.dividend_type in {"CASH_DPS", "CASH_DPS_ANNUAL"}
            ]
            latest_annual = annual_dividends[0] if annual_dividends else None
            last_year = now_kst().year - 1
            last_year_dividend = next(
                (item for item in annual_dividends if item.business_year == last_year),
                None,
            )
            interim_dividend = next(
                (
                    item
                    for item in ordered_dividends
                    if item.dividend_type
                    in {"CASH_DPS_Q1", "CASH_DPS_H1", "CASH_DPS_Q3"}
                    and item.dps is not None
                    and item.dps > 0
                ),
                None,
            )
            metric_columns = st.columns(4)
            metric_columns[0].metric(
                "최근 확정 연간 주당배당금",
                (
                    _format_value(latest_annual.dps, latest_annual.currency)
                    if latest_annual is not None
                    else "확인 불가"
                ),
            )
            metric_columns[1].metric(
                "최신 연간 DPS 기준 배당률",
                _format_dividend_yield(
                    latest_annual.dps if latest_annual is not None else None,
                    latest_price,
                ),
            )
            metric_columns[2].metric(
                "배당 주기",
                _dividend_frequency(snapshot.dividends),
            )
            metric_columns[3].metric(
                f"{last_year}년 주당배당금",
                (
                    _format_value(
                        last_year_dividend.dps,
                        last_year_dividend.currency,
                    )
                    if last_year_dividend is not None
                    else "확인 불가"
                ),
            )
            if latest_price is not None:
                st.caption(
                    "배당률은 최신 확정 연간 DPS를 "
                    f"{latest_price.trade_date.isoformat()} 종가 "
                    f"{latest_price.close_price:,.0f}원으로 나눈 단순 배당률입니다."
                )
            if interim_dividend is not None:
                st.info(
                    f"{interim_dividend.business_year}년 "
                    f"{_DIVIDEND_PERIOD_LABELS.get(interim_dividend.dividend_type or '', '중간')} "
                    "주당배당금: "
                    f"{_format_value(interim_dividend.dps, interim_dividend.currency)}"
                )
            st.dataframe(
                [
                    {
                        "지급 사업연도": item.business_year,
                        "보고 구분": _DIVIDEND_PERIOD_LABELS.get(
                            item.dividend_type or "",
                            "확인 불가",
                        ),
                        "주식종류": item.stock_kind or "확인 불가",
                        "누적 주당 현금배당금": _format_value(
                            item.dps,
                            item.currency,
                        ),
                        "현재 주가 기준 단순 배당률": _format_dividend_yield(
                            item.dps,
                            latest_price,
                        ),
                        "현금배당 총액": _format_value(
                            item.total_amount,
                            item.currency,
                        ),
                        "공시 접수일": _format_date(item.filing_date),
                        "확정·추정": (
                            "확정"
                            if item.is_confirmed is True and item.is_estimate is False
                            else "확인 불가"
                        ),
                        "출처": "OpenDART 배당에 관한 사항",
                        "원문": item.source_url or "확인 불가",
                    }
                    for item in ordered_dividends
                ],
                width="stretch",
                hide_index=True,
            )

    with finance_tab:
        if not snapshot.financial_accounts:
            st.warning("OpenDART 재무제표 데이터가 없습니다.")
        else:
            st.dataframe(
                [
                    {
                        "지표": item.metric_code,
                        "원 계정명": item.account_name,
                        "당기값": _format_value(item.value, item.currency),
                        "누적값": _format_value(
                            item.cumulative_value,
                            item.currency,
                        ),
                        "TTM": _format_value(item.ttm_value, item.currency),
                        "연결·별도": item.fs_div.value,
                        "사업연도": item.business_year,
                        "보고서코드": item.report_code,
                        "보고서 제출일": item.filing_date.isoformat(),
                        "접수번호": item.receipt_no,
                        "계산 구분": (item.calculation_source or "공식 원자료"),
                        "원문": item.source_url or "확인 불가",
                    }
                    for item in snapshot.financial_accounts
                ],
                width="stretch",
                hide_index=True,
            )
            st.caption(
                "계정 매핑 실패값은 0으로 바꾸지 않습니다. TTM은 공식 "
                "당기·누적·전기누적 값이 모두 있을 때만 자체 계산합니다."
            )
        annual_history = [
            item
            for item in snapshot.financial_history
            if item.currency == "KRW"
            and item.value is not None
            and item.metric_code in {code for code, _ in _FINANCIAL_COMPARISON_METRICS}
        ]
        if annual_history:
            st.subheader("최근 3개년 재무 비교")
            st.caption("사업보고서 연간 확정값 · 연결재무제표 우선 · 단위 억원")
            years = sorted({item.business_year for item in annual_history})
            values_by_key = {
                (item.metric_code, item.business_year): item.value
                for item in annual_history
            }
            comparison_rows = []
            available_metrics: list[tuple[str, str]] = []
            for metric_code, metric_label in _FINANCIAL_COMPARISON_METRICS:
                metric_values = {
                    year: values_by_key.get((metric_code, year)) for year in years
                }
                if not any(value is not None for value in metric_values.values()):
                    continue
                available_metrics.append((metric_code, metric_label))
                comparison_rows.append(
                    {
                        "지표": metric_label,
                        **{
                            str(year): (
                                float(
                                    (value / Decimal(100_000_000)).quantize(
                                        Decimal("0.01")
                                    )
                                )
                                if value is not None
                                else None
                            )
                            for year, value in metric_values.items()
                        },
                    }
                )
            st.dataframe(
                comparison_rows,
                width="stretch",
                hide_index=True,
            )
            metric_labels = {
                metric_label: metric_code
                for metric_code, metric_label in available_metrics
            }
            selected_metric_label = st.selectbox(
                "추이 그래프 지표",
                options=list(metric_labels),
                key=f"financial-history-metric-{snapshot.symbol}",
            )
            selected_metric_code = metric_labels[selected_metric_label]
            selected_values = {
                year: value
                for year in years
                if (value := values_by_key.get((selected_metric_code, year)))
                is not None
            }
            graph_modes = (
                [
                    "첫해=100 변화지수",
                    "전년 대비 증감률(%)",
                    "실제 금액(억원)",
                ]
                if selected_values
                and all(value > 0 for value in selected_values.values())
                else ["실제 금액(억원)"]
            )
            graph_mode = st.radio(
                "그래프 표시 방식",
                options=graph_modes,
                horizontal=True,
                key=f"financial-history-mode-{snapshot.symbol}",
            )
            chart_rows, y_axis_title = _financial_chart_rows(
                selected_values,
                graph_mode,
            )
            chart_data = alt.Data(values=chart_rows)
            base_chart = alt.Chart(chart_data).encode(
                x=alt.X(
                    "사업연도:O",
                    title=None,
                    sort=[str(row["사업연도"]) for row in chart_rows],
                    axis=alt.Axis(
                        labelAngle=0,
                        labelOverlap=False,
                        labelPadding=8,
                    ),
                ),
                y=alt.Y(
                    "값:Q",
                    title=y_axis_title,
                    scale=alt.Scale(zero=False, padding=20),
                ),
                tooltip=[
                    alt.Tooltip("사업연도:O"),
                    alt.Tooltip(
                        "값:Q",
                        title=y_axis_title,
                        format=",.2f",
                    ),
                ],
            )
            trend_line = base_chart.mark_line(point=True, strokeWidth=3)
            value_labels = base_chart.mark_text(
                dy=-14,
                fontSize=12,
            ).encode(text=alt.Text("값:Q", format=",.2f"))
            st.altair_chart(
                (trend_line + value_labels).properties(
                    height=320,
                    title=f"{selected_metric_label} 3개년 추이",
                ),
                width="stretch",
            )
        else:
            st.info("최근 3개년 연간 재무 비교 데이터가 없습니다.")

    with audit_tab:
        audit = snapshot.latest_audit
        if audit is None:
            st.warning("최신 감사의견 데이터가 없습니다.")
        else:
            st.write("감사의견:", audit.opinion or "확인 불가")
            st.write("감사인:", audit.auditor or "확인 불가")
            st.write("대상 사업연도:", audit.business_year)
            st.write("보고서 제출일:", _format_date(audit.filing_date))
            st.write("접수번호:", audit.receipt_no)
            st.write(
                "계속기업 불확실성:",
                _format_going_concern(
                    audit.going_concern_status,
                    audit.going_concern_risk,
                ),
            )
            st.write("강조사항 확인 상태:", audit.emphasis_status)
            if audit.emphasis_matter:
                st.text(audit.emphasis_matter)
            st.write("원문:", audit.source_url or "확인 불가")

    with technical_tab:
        technical = snapshot.technical
        if technical.state != DataState.AVAILABLE:
            st.warning(
                technical.error_message
                or "수정가격 확인이 없어 기술지표를 계산할 수 없습니다."
            )
        else:
            st.dataframe(
                [
                    {"지표": "Wilder RSI 14", "값": technical.rsi_14},
                    {"지표": "SMA 20", "값": technical.sma_20},
                    {"지표": "SMA 60", "값": technical.sma_60},
                    {"지표": "SMA 120", "값": technical.sma_120},
                    {"지표": "SMA 200", "값": technical.sma_200},
                    {"지표": "ATR 14", "값": technical.atr_14},
                    {
                        "지표": "52주 고점 대비 낙폭",
                        "값": technical.drawdown_52_week,
                    },
                ],
                width="stretch",
                hide_index=True,
            )
            st.caption(
                f"자체 계산값 · 기준일 {_format_date(technical.as_of_date)} · "
                f"가격 출처 {technical.price_source or '확인 불가'} · "
                f"규칙 {technical.rule_version}"
            )

    with source_tab:
        if not snapshot.dividend_decisions:
            st.info("현금·현물배당결정 공시가 수집되지 않았습니다.")
        else:
            st.dataframe(
                [
                    {
                        "보고서명": item.report_name,
                        "공시 접수일": item.receipt_date.isoformat(),
                        "접수번호": item.receipt_no,
                        "정정 여부": "정정" if item.is_correction else "원공시",
                        "원문": item.source_url or "확인 불가",
                    }
                    for item in snapshot.dividend_decisions
                ],
                width="stretch",
                hide_index=True,
            )


def render_stock_search(settings: Settings) -> None:
    recommendation_context: RecommendationDecision | None = None
    if st.session_state.get("stock_detail_origin") == "추천종목":
        st.button(
            "← 추천 종목으로 돌아가기",
            key="return-to-recommendations",
            on_click=_return_to_recommendations,
        )
        payload = st.session_state.get("stock_detail_recommendation")
        if isinstance(payload, dict):
            try:
                recommendation_context = RecommendationDecision.model_validate(payload)
            except ValueError:
                recommendation_context = None
    st.markdown(
        '<div class="status-kicker">Phase 2 · Filters and scoring</div>',
        unsafe_allow_html=True,
    )
    st.title(
        "추천 종목 상세" if recommendation_context is not None else "국내 종목 검색"
    )
    st.caption(
        "KRX 유가증권·코스닥 종목기본정보와 OpenDART 고유번호에 "
        "연결된 종목을 같은 구조로 검색합니다."
    )
    dart_status = next(
        item
        for item in get_connection_statuses(settings)
        if item.provider == "OpenDART"
    )
    dart_message = f"OpenDART: {dart_status.state.value} · {dart_status.detail}"
    if dart_status.state == ConnectionState.CONNECTED:
        st.success(dart_message)
    elif dart_status.state in {
        ConnectionState.STALE,
        ConnectionState.NOT_CONFIGURED,
    }:
        st.warning(dart_message)
    else:
        st.error(dart_message)
    if recommendation_context is not None:
        query = recommendation_context.symbol
        st.session_state["stock_search_query"] = query
        st.caption(
            f"추천 결과에서 선택한 종목 · {recommendation_context.name} "
            f"({recommendation_context.symbol})"
        )
    else:
        query = st.text_input(
            "종목명 또는 6자리 종목코드",
            placeholder="종목명 또는 6자리 종목코드 입력",
            key="stock_search_query",
        ).strip()

    service: UniverseService | None = None
    price_service: PriceService | None = None
    latest_prices: dict[str, LatestDailyPrice] = {}
    dividend_reference_prices: dict[str, LatestDailyPrice] = {}
    try:
        service = UniverseService(settings)
        stock_count = service.stock_count()
        if stock_count == 0:
            st.error(
                "실제 KRX 종목 데이터가 없습니다. "
                "API 키를 설정하고 종목 마스터 수집 명령을 실행하세요."
            )
            st.caption("빈 목록을 유지하며 예시 종목을 대신 표시하지 않습니다.")
            return
        st.caption(f"저장된 공식 종목 레코드: {stock_count:,}건")
        if not query:
            st.info("검색어를 입력하면 공식 데이터에 저장된 종목만 표시합니다.")
            return

        results = service.search(query)
        if results:
            price_service = PriceService(settings)
            result_symbols = [item.symbol for item in results]
            latest_prices = price_service.latest_for_symbols(result_symbols)
            dividend_reference_prices = price_service.latest_adjusted_for_symbols(
                result_symbols
            )
    except (SQLAlchemyError, OSError, ValueError) as exc:
        st.error(f"종목 검색 초기화 실패: {type(exc).__name__}")
        st.caption("DB migration과 DATABASE_URL 설정을 확인하세요.")
        return
    finally:
        if service is not None:
            service.close()
        if price_service is not None:
            price_service.close()

    if not results:
        st.warning("검색 결과가 없습니다.")
        return

    rows = []
    for item in results:
        latest_price = latest_prices.get(item.symbol)
        market_label = (
            "유가증권"
            if item.is_kospi is True
            else "코스닥"
            if item.is_kospi is False
            else item.market_name or "국내주식"
        )
        rows.append(
            {
                "종목명": item.name,
                "종목코드": item.symbol,
                "최근 확정종가": _format_price(latest_price),
                "가격 기준일": (
                    latest_price.trade_date.isoformat()
                    if latest_price is not None
                    else "확인 불가"
                ),
                "가격 수집시각": (
                    _format_timestamp(latest_price.collected_at)
                    if latest_price is not None
                    else "확인 불가"
                ),
                "가격 출처·상태": (
                    f"KRX {market_label} 일별매매정보 · 전일종가"
                    if latest_price is not None
                    else "데이터 연결 필요"
                ),
                "공식 시장": (
                    "KOSPI"
                    if item.is_kospi is True
                    else "KOSDAQ"
                    if item.is_kospi is False
                    else "확인 불가"
                ),
                "시장구분": item.market_name or "확인 불가",
                "상품구분": (
                    item.official_product_name or _PRODUCT_LABELS[item.product_type]
                ),
                "정규화 상품": _PRODUCT_LABELS[item.product_type],
                "보통주·우선주": (
                    item.official_share_class_name
                    or _SHARE_CLASS_LABELS[item.share_class]
                ),
                "상장상태": _LISTING_LABELS[item.listing_status],
                "OpenDART 고유번호": item.dart_corp_code or "미매핑",
                "데이터 출처": (
                    "KRX / OpenDART" if item.dart_corp_code else item.source_provider
                ),
                "데이터 기준일": (
                    f"KRX {_format_timestamp(item.as_of_at)} / "
                    f"OpenDART 변경일 {_format_date(item.dart_modified_on)}"
                ),
                "수집시각": (
                    f"KRX {_format_timestamp(item.collected_at)} / "
                    "OpenDART "
                    f"{_format_timestamp(item.dart_collected_at)}"
                ),
                "데이터 품질": (
                    f"{_QUALITY_LABELS[item.quality_state]} / "
                    "OpenDART "
                    f"{_DATA_STATE_LABELS[item.dart_data_state]}"
                ),
            }
        )
    if recommendation_context is None:
        with st.expander(f"검색 결과 {len(results)}건 · 목록 및 원자료"):
            st.dataframe(
                [
                    {
                        key: row[key]
                        for key in (
                            "종목명",
                            "종목코드",
                            "최근 확정종가",
                            "가격 기준일",
                            "가격 출처·상태",
                            "시장구분",
                            "상품구분",
                            "상장상태",
                        )
                    }
                    for row in rows
                ],
                width="stretch",
                hide_index=True,
            )
            if st.toggle("상세 설명 · 검색 결과 원자료 표시"):
                st.dataframe(rows, width="stretch", hide_index=True)
            st.caption(
                "검색 목록은 KRX 확정 일별종가, 상세 화면은 KIS 5분 갱신 현재가를 "
                "우선 표시합니다. RSI는 검증된 수정주가로만 계산하며 강제필터·점수는 "
                "계산 결과가 저장된 경우에만 표시합니다."
            )
        labels = {f"{item.name} ({item.symbol})": item.symbol for item in results}
        selected_label = st.selectbox(
            "세부 분석 종목",
            options=list(labels),
        )
        selected_symbol = labels[selected_label]
    else:
        selected_symbol = recommendation_context.symbol
    selected_stock = next(item for item in results if item.symbol == selected_symbol)
    stock_chart_container = st.container()
    default_order_amount = int(
        settings.phase2_planned_order_amount_krw or Decimal(1000000)
    )
    planned_order_amount = st.number_input(
        "Phase 2 예정 주문금액 (원)",
        min_value=0,
        value=default_order_amount,
        step=100_000,
        help="유동성 필터의 주문금액 대비 거래대금 비율 계산에 사용합니다.",
    )
    refresh_column, score_column = st.columns(2)
    with refresh_column:
        refresh_official_data = st.button(
            "선택 종목 공식 데이터 새로고침",
            width="stretch",
        )
    with score_column:
        recalculate_phase2 = st.button(
            "선택 종목 Phase 2 다시 계산",
            type="primary",
            width="stretch",
        )
    analysis_service: StockAnalysisService | None = None
    scoring_service: Phase2ScoringService | None = None
    entry_service: EntryReadinessService | None = None
    chart_price_service: PriceService | None = None
    detail_event_service: EventService | None = None
    index_service: IndexService | None = None
    phase2_result: Phase2Result | None = None
    entry_readiness: EntryReadiness | None = None
    phase5_snapshot: Phase5Snapshot | None = None
    valuation_reference: ValuationReference | None = None
    price_history: list[AdjustedPricePoint] = []
    index_history: list[IndexPoint] = []
    auto_refreshed = False
    try:
        analysis_service = StockAnalysisService(settings)
        chart_price_service = PriceService(settings)
        snapshot = analysis_service.snapshot(selected_symbol)
        price_history = chart_price_service.history_for_symbol(
            selected_symbol,
            limit=260,
        )
        auto_refresh_key = f"stock-detail-auto-refresh-v2-{selected_symbol}"
        detail_as_of_date = now_kst().date()
        financial_needed, price_needed = _stock_detail_refresh_needs(
            snapshot,
            price_history,
            as_of_date=detail_as_of_date,
        )
        refresh_financial = (
            financial_needed
            and settings.dart_api_key is not None
            and selected_stock.dart_corp_code is not None
        )
        refresh_price = (
            price_needed
            and settings.kis_app_key is not None
            and settings.kis_app_secret is not None
        )
        refresh_market_status = recommendation_context is not None
        should_auto_refresh = (
            not refresh_official_data
            and not st.session_state.get(auto_refresh_key, False)
            and selected_stock.dart_corp_code is not None
            and (refresh_financial or refresh_price or refresh_market_status)
        )
        if should_auto_refresh:
            st.session_state[auto_refresh_key] = True
            with st.spinner(
                "부족한 차트·재무와 KIND 시장상태를 증분 보충하고 있습니다."
            ):
                financial_summary = None
                price_summary = None
                market_summary = None
                if refresh_financial:
                    financial_summary = asyncio.run(
                        analysis_service.refresh(
                            symbol=selected_symbol,
                            as_of_date=detail_as_of_date,
                            years=3,
                            incremental=True,
                        )
                    )
                if refresh_price:
                    latest_price_date = max(
                        (item.trade_date for item in price_history),
                        default=None,
                    )
                    lookback_days = (
                        500
                        if len(price_history) < 126 or latest_price_date is None
                        else max(
                            30,
                            (detail_as_of_date - latest_price_date).days + 14,
                        )
                    )
                    price_summary = asyncio.run(
                        chart_price_service.refresh_adjusted_history(
                            symbol=selected_symbol,
                            as_of_date=detail_as_of_date,
                            lookback_days=lookback_days,
                        )
                    )
                if refresh_market_status:
                    market_status_service = MarketStatusService(settings)
                    try:
                        market_summary = asyncio.run(
                            market_status_service.refresh(
                                symbol=selected_symbol,
                                as_of_date=detail_as_of_date,
                            )
                        )
                    finally:
                        market_status_service.close()
            auto_refreshed = True
            snapshot = analysis_service.snapshot(selected_symbol)
            price_history = chart_price_service.history_for_symbol(
                selected_symbol,
                limit=260,
            )
            refreshed_parts: list[str] = []
            if price_summary is not None:
                refreshed_parts.append(f"수정주가 {price_summary.stored:,}건")
            if financial_summary is not None:
                refreshed_parts.extend(
                    (
                        f"재무계정 {financial_summary.accounts_stored:,}건",
                        f"배당 {financial_summary.dividends_stored:,}건",
                    )
                )
            if market_summary is not None:
                refreshed_parts.append(
                    "KIND 시장상태 "
                    + (
                        "확인"
                        if market_summary.state == DataState.AVAILABLE
                        else "일부 미확인"
                    )
                )
            st.success("상세 데이터 자동 보충 완료 · " + " · ".join(refreshed_parts))
        if refresh_official_data:
            with st.spinner("OpenDART 재무·배당·감사 데이터를 수집하고 있습니다."):
                financial_summary = asyncio.run(
                    analysis_service.refresh(
                        symbol=selected_symbol,
                        as_of_date=now_kst().date(),
                        years=5,
                    )
                )
            adjusted_price_service = PriceService(settings)
            try:
                with st.spinner("KIS 수정주가 일봉을 수집하고 있습니다."):
                    price_summary = asyncio.run(
                        adjusted_price_service.refresh_adjusted_history(
                            symbol=selected_symbol,
                            as_of_date=now_kst().date(),
                        )
                    )
            finally:
                adjusted_price_service.close()
            market_status_service = MarketStatusService(settings)
            try:
                with st.spinner("KIND 공식 시장상태를 확인하고 있습니다."):
                    market_summary = asyncio.run(
                        market_status_service.refresh(
                            symbol=selected_symbol,
                            as_of_date=now_kst().date(),
                        )
                    )
            finally:
                market_status_service.close()
            event_service = EventService(settings)
            try:
                with st.spinner("OpenDART 중요공시와 기업 이벤트를 갱신하고 있습니다."):
                    event_summary = asyncio.run(
                        event_service.refresh(
                            symbol=selected_symbol,
                            as_of_date=now_kst().date(),
                        )
                    )
            finally:
                event_service.close()
            valuation_service = ValuationDataService(settings)
            try:
                with st.spinner(
                    "KIS·KRX·OpenDART PER/PBR 비교 데이터를 갱신하고 있습니다."
                ):
                    valuation_summary = asyncio.run(
                        valuation_service.refresh(
                            symbol=selected_symbol,
                            as_of_date=now_kst().date(),
                        )
                    )
            finally:
                valuation_service.close()
            if (
                financial_summary.state == DataState.AVAILABLE.value
                and price_summary.state == DataState.AVAILABLE.value
                and market_summary.state == DataState.AVAILABLE
                and event_summary.state in {DataState.AVAILABLE, DataState.MISSING}
                and valuation_summary.state == DataState.AVAILABLE
            ):
                st.success(
                    "공식 데이터 새로고침 완료 · "
                    f"재무계정 {financial_summary.accounts_stored:,}건 · "
                    f"감사의견 {financial_summary.audit_opinions_stored:,}건 · "
                    f"수정주가 {price_summary.stored:,}건 · "
                    "KIND 시장상태·OpenDART 기업 이벤트·PER/PBR 확인 완료"
                )
            else:
                st.warning(
                    "일부 공식 데이터가 갱신되지 않았습니다. "
                    f"OpenDART={financial_summary.state}, "
                    f"KIS={price_summary.state}, "
                    f"KIND={market_summary.state.value}, "
                    f"이벤트={event_summary.state.value}, "
                    f"밸류에이션={valuation_summary.state.value}"
                )
        snapshot = analysis_service.snapshot(selected_symbol)
        price_history = chart_price_service.history_for_symbol(
            selected_symbol,
            limit=260,
        )
        detail_event_service = EventService(settings)
        phase5_snapshot = detail_event_service.snapshot(selected_symbol)
        index_service = IndexService(settings)
        index_history = index_service.history(index_name="코스피", limit=100)
        scoring_service = Phase2ScoringService(settings)
        phase2_result = scoring_service.latest(selected_symbol)
        if (
            recalculate_phase2
            or refresh_official_data
            or auto_refreshed
            or phase2_result is None
        ):
            phase2_result = scoring_service.evaluate(
                selected_symbol,
                as_of_at=now_kst(),
                planned_order_amount=Decimal(str(planned_order_amount)),
            )
            if recalculate_phase2 or refresh_official_data or auto_refreshed:
                st.success(
                    "선택 종목의 Phase 2 결과를 최신 저장 데이터로 계산했습니다."
                )
        entry_service = EntryReadinessService(settings)
        entry_readiness = entry_service.latest(
            phase2_result.individual_entry_score if phase2_result is not None else None
        )
        valuation_reference_service = ValuationDataService(settings)
        try:
            valuation_reference = valuation_reference_service.reference_for_symbol(
                selected_symbol,
                as_of_date=now_kst().date(),
            )
        finally:
            valuation_reference_service.close()
    except (SQLAlchemyError, OSError, ValueError) as exc:
        st.error(f"종목 분석 조회 실패: {type(exc).__name__}")
        return
    finally:
        if analysis_service is not None:
            analysis_service.close()
        if scoring_service is not None:
            scoring_service.close()
        if entry_service is not None:
            entry_service.close()
        if chart_price_service is not None:
            chart_price_service.close()
        if detail_event_service is not None:
            detail_event_service.close()
        if index_service is not None:
            index_service.close()
    if snapshot is None:
        st.warning("종목 분석 데이터를 조회할 수 없습니다.")
        return
    with stock_chart_container:
        _render_stock_price_panel(
            settings,
            selected_stock,
            latest_prices.get(selected_symbol)
            or dividend_reference_prices.get(selected_symbol),
            price_history,
            snapshot,
            phase2_result,
            phase5_snapshot,
            index_history,
            valuation_reference,
        )
        if (
            recommendation_context is not None
            and recommendation_context.symbol == selected_symbol
        ):
            _render_recommendation_context(
                recommendation_context,
                entry_threshold=settings.phase4_ready_entry_score,
            )
    _render_analysis_tabs(
        snapshot,
        phase2_result,
        entry_readiness,
        dividend_reference_prices.get(selected_symbol),
    )
