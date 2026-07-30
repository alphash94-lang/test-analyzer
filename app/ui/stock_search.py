from __future__ import annotations

from datetime import date, datetime

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.models.financial import StockAnalysisSnapshot
from app.models.metadata import DataState
from app.models.price import LatestDailyPrice
from app.models.scoring import Phase2Result
from app.models.stock import (
    ListingStatus,
    ProductType,
    ShareClass,
    StockQualityState,
)
from app.services.phase2_service import Phase2ScoringService
from app.services.price_service import PriceService
from app.services.stock_analysis_service import StockAnalysisService
from app.services.universe_service import UniverseService

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


def _format_score(value: object) -> str:
    return "추천 계산 불가" if value is None else f"{value}/100"


def _format_going_concern(
    status: str,
    risk: bool | None,
) -> str:
    if status != "VERIFIED" or risk is None:
        return "확인 불가"
    return "중대한 불확실성 확인" if risk else "중대한 불확실성 없음"


def _render_phase2_score(result: Phase2Result | None) -> None:
    if result is None:
        st.warning(
            "Phase 2 강제필터·점수 계산 결과가 없습니다. "
            "저장된 공식 데이터를 확인한 뒤 점수 계산 명령을 실행하세요."
        )
        return
    st.write("기본 투자매력:", _format_score(result.investment_score))
    st.write(
        "개별 종목 진입 구성요소:",
        _format_score(result.individual_entry_score),
    )
    st.write("전체 진입준비:", "Phase 3 시장 입력 전 계산 보류")
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
        st.error("누락된 핵심 데이터: " + ", ".join(result.missing_core_data))
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
        use_container_width=True,
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
            use_container_width=True,
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
            use_container_width=True,
            hide_index=True,
        )


def _render_analysis_tabs(
    snapshot: StockAnalysisSnapshot,
    phase2_result: Phase2Result | None,
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
            "차트·진입시점",
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
            (
                "점수 계산 가능"
                if phase2_result is not None and phase2_result.recommendation_computable
                else "추천 계산 불가"
            ),
        )

    with score_tab:
        _render_phase2_score(phase2_result)

    with dividend_tab:
        if not snapshot.dividends:
            st.warning("OpenDART 최근 5개 사업연도 확정 DPS 데이터가 없습니다.")
        else:
            st.dataframe(
                [
                    {
                        "지급 사업연도": item.business_year,
                        "주식종류": item.stock_kind or "확인 불가",
                        "확정 DPS": _format_value(
                            item.dps,
                            item.currency,
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
                    for item in snapshot.dividends
                ],
                use_container_width=True,
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
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "계정 매핑 실패값은 0으로 바꾸지 않습니다. TTM은 공식 "
                "당기·누적·전기누적 값이 모두 있을 때만 자체 계산합니다."
            )

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
                use_container_width=True,
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
                use_container_width=True,
                hide_index=True,
            )


def render_stock_search(settings: Settings) -> None:
    st.markdown(
        '<div class="status-kicker">Phase 2 · Filters and scoring</div>',
        unsafe_allow_html=True,
    )
    st.title("코스피 종목 검색")
    st.caption(
        "KRX 유가증권 종목기본정보와 OpenDART 고유번호에 연결된 종목만 검색합니다."
    )
    dart_key_configured = bool(
        settings.dart_api_key and settings.dart_api_key.get_secret_value().strip()
    )
    if dart_key_configured:
        st.info(
            "OpenDART: 연결 미검증 · 실제 수집이 성공하기 전에는 "
            "재무·배당·감사 데이터를 최신으로 간주하지 않습니다."
        )
    else:
        st.warning(
            "OpenDART: 키 미설정 · DART_API_KEY가 없어 "
            "재무·배당·감사 데이터를 수집할 수 없습니다."
        )
    query = st.text_input(
        "종목명 또는 6자리 종목코드",
        placeholder="종목명 또는 6자리 종목코드 입력",
    ).strip()

    service: UniverseService | None = None
    price_service: PriceService | None = None
    latest_prices: dict[str, LatestDailyPrice] = {}
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
            latest_prices = price_service.latest_for_symbols(
                [item.symbol for item in results]
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
                    "KRX 유가증권 일별매매정보 · 전일종가"
                    if latest_price is not None
                    else "데이터 연결 필요"
                ),
                "KOSPI 여부": ("확인됨" if item.is_kospi is True else "확인 불가"),
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
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption(
        "KRX 확정 일별종가만 표시합니다. KRX 응답에서 수정주가 여부를 "
        "확인할 수 없으면 RSI를 계산하지 않습니다. 실시간가는 표시하지 "
        "않으며 "
        "강제필터·점수는 계산 결과가 저장된 경우에만 표시합니다."
    )
    labels = {f"{item.name} ({item.symbol})": item.symbol for item in results}
    selected_label = st.selectbox(
        "세부 분석 종목",
        options=list(labels),
    )
    analysis_service: StockAnalysisService | None = None
    scoring_service: Phase2ScoringService | None = None
    phase2_result: Phase2Result | None = None
    try:
        analysis_service = StockAnalysisService(settings)
        snapshot = analysis_service.snapshot(labels[selected_label])
        scoring_service = Phase2ScoringService(settings)
        phase2_result = scoring_service.latest(labels[selected_label])
    except (SQLAlchemyError, OSError, ValueError) as exc:
        st.error(f"종목 분석 조회 실패: {type(exc).__name__}")
        return
    finally:
        if analysis_service is not None:
            analysis_service.close()
        if scoring_service is not None:
            scoring_service.close()
    if snapshot is None:
        st.warning("종목 분석 데이터를 조회할 수 없습니다.")
        return
    _render_analysis_tabs(snapshot, phase2_result)
