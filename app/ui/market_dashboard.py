from __future__ import annotations

from decimal import Decimal

import streamlit as st

from app.config import Settings
from app.db.session import create_db_engine, create_session_factory
from app.models.status import ConnectionState
from app.repositories.market_analysis_repository import MarketAnalysisRepository
from app.services.connection_status import get_connection_statuses
from app.utils.dates import restore_database_kst

_REGIME_LABELS = {
    "RED": "적색 · 투매",
    "ORANGE": "주황 · 안정화",
    "YELLOW": "황색 · 회복",
    "GREEN": "녹색 · 순환상승",
    "UNCERTAIN": "불확실",
}
_SHOCK_LABELS = {
    "SEMICONDUCTOR_LED": "반도체 주도 하락",
    "BROAD_SELLOFF": "시장 전반 투매",
    "MIXED": "혼합형",
    "UNCERTAIN": "불확실",
}
_PROXY_LABELS = {
    "OFFICIAL_INDEX": "공식 반도체 지수",
    "SELF_CALCULATED_PROXY": "자체 반도체 프록시 지수",
    "NOT_AVAILABLE": "반도체 분류 확인 불가",
    "NOT_APPLICABLE": "해당 없음",
}
_TIMING_LABELS = {
    "REALTIME": "실시간",
    "DELAYED": "지연 시세",
    "PREVIOUS_CLOSE": "확정 종가 기반",
    "PERIODIC_DISCLOSURE": "정기공시",
    "NOT_APPLICABLE": "해당 없음",
    "UNKNOWN": "확인 불가",
}


def _format_value(value: Decimal | None, text: str | None, unit: str | None) -> str:
    if text is not None:
        return text
    if value is None:
        return "확인 불가"
    if unit == "rate":
        return f"{value * Decimal(100):,.2f}%"
    if unit == "score_0_100":
        return f"{value:,.1f}/100"
    return f"{value:,.4f}"


def _render_input_connection_reasons(settings: Settings) -> None:
    relevant = {"KRX", "OpenDART", "한국투자증권"}
    for status in get_connection_statuses(settings):
        if status.provider in relevant:
            st.caption(
                f"{status.provider} 연결상태: {status.state.value} · {status.detail}"
            )


def render_market_dashboard(settings: Settings) -> None:
    st.title("시장국면 대시보드")
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    try:
        with sessions() as session:
            snapshot, metrics, contributions = MarketAnalysisRepository.latest(session)
            if snapshot is None:
                krx = next(
                    status
                    for status in get_connection_statuses(settings)
                    if status.provider == "KRX"
                )
                st.warning(
                    "저장된 Phase 3 시장 분석이 없습니다. "
                    f"KRX 연결상태: {krx.state.value} · {krx.detail}",
                    icon="⚠️",
                )
                st.info(
                    "`python -m scripts.update_daily_index --as-of YYYY-MM-DD`로 "
                    "지수를 수집하고, 검증된 수정가격·공식 산업분류·확정 배당 "
                    "입력 후 `python -m scripts.update_phase3_market`을 실행하세요."
                )
                if krx.state == ConnectionState.NOT_CONFIGURED:
                    st.caption("가짜 시장국면이나 샘플 시장 숫자를 표시하지 않습니다.")
                return

            st.caption(
                f"분석 기준시각: "
                f"{restore_database_kst(snapshot.as_of_at).strftime('%Y-%m-%d %H:%M:%S KST')}"
                f" · 규칙: {snapshot.rule_version}"
            )
            if snapshot.data_state != "AVAILABLE":
                missing = ", ".join(snapshot.missing_core_data)
                st.warning(
                    "핵심 데이터가 부족해 시장국면을 확정할 수 없습니다. "
                    f"누락: {missing}",
                    icon="⚠️",
                )
                _render_input_connection_reasons(settings)
            col1, col2, col3 = st.columns(3)
            col1.metric(
                "시장충격",
                _SHOCK_LABELS.get(
                    snapshot.shock_classification,
                    snapshot.shock_classification,
                ),
            )
            col2.metric(
                "시장국면",
                _REGIME_LABELS.get(
                    snapshot.market_regime,
                    snapshot.market_regime,
                ),
            )
            col3.metric(
                "반도체 기준",
                _PROXY_LABELS.get(snapshot.proxy_kind, snapshot.proxy_kind),
            )
            st.caption(snapshot.explanation)

            st.subheader("핵심 지표와 데이터 근거")
            st.dataframe(
                [
                    {
                        "지표": metric.metric_label,
                        "값": _format_value(
                            metric.value,
                            metric.text_value,
                            metric.unit,
                        ),
                        "상태": metric.state,
                        "출처": (
                            f"{metric.source_provider or '확인 불가'} · "
                            f"{metric.source_function or '확인 불가'}"
                        ),
                        "기준시각": (
                            restore_database_kst(metric.as_of_at).strftime(
                                "%Y-%m-%d %H:%M:%S KST"
                            )
                            if metric.as_of_at is not None
                            else "확인 불가"
                        ),
                        "수집시각": (
                            restore_database_kst(metric.collected_at).strftime(
                                "%Y-%m-%d %H:%M:%S KST"
                            )
                            if metric.collected_at is not None
                            else "확인 불가"
                        ),
                        "계산방법": metric.calculation_method,
                        "데이터 품질": metric.data_quality,
                        "시세구분": _TIMING_LABELS.get(
                            metric.data_timing,
                            metric.data_timing,
                        ),
                        "공식·자체": (
                            f"{metric.source_kind} · "
                            f"{_PROXY_LABELS.get(metric.proxy_kind, metric.proxy_kind)}"
                        ),
                    }
                    for metric in metrics
                ],
                hide_index=True,
                width="stretch",
            )
            if contributions:
                st.subheader("종목별 지수 기여도 설명 추정치")
                st.caption(
                    "전일 전체 비교종목 시가총액 비중 × 당일 수정가격 수익률입니다. "
                    "공식 KOSPI 지수 포인트 기여도나 인과관계가 아닙니다."
                )
                st.dataframe(
                    [
                        {
                            "종목": f"{row.name} ({row.symbol})",
                            "반도체": (
                                "예"
                                if row.is_semiconductor is True
                                else (
                                    "아니오"
                                    if row.is_semiconductor is False
                                    else "미분류"
                                )
                            ),
                            "당일 수익률": f"{row.return_rate * Decimal(100):,.3f}%",
                            "전일 비중": f"{row.previous_weight * Decimal(100):,.3f}%",
                            "기여도 추정": f"{row.contribution * Decimal(100):,.4f}%p",
                            "가격 출처": row.source_provider,
                            "시가총액 출처": row.market_cap_source_provider,
                            "분류 출처": row.classification_source or "확인 불가",
                            "기준일": row.as_of_date.isoformat(),
                            "수집시각": (
                                restore_database_kst(row.collected_at).strftime(
                                    "%Y-%m-%d %H:%M:%S KST"
                                )
                                if row.collected_at is not None
                                else "확인 불가"
                            ),
                            "시세구분": _TIMING_LABELS.get(
                                row.data_timing,
                                row.data_timing,
                            ),
                            "계산방법": row.calculation_method,
                            "데이터 품질": row.data_quality,
                            "공식·자체": (
                                f"{row.source_kind} · "
                                f"{_PROXY_LABELS.get(row.proxy_kind, row.proxy_kind)}"
                            ),
                        }
                        for row in contributions
                    ],
                    hide_index=True,
                    width="stretch",
                )
    finally:
        engine.dispose()
