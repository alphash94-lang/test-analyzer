from __future__ import annotations

import asyncio
from datetime import date, datetime, time
from decimal import Decimal

import altair as alt
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.db.models.market_analysis import (
    MarketContributionRecord,
    MarketMetricRecord,
)
from app.db.session import create_db_engine, create_session_factory
from app.models.metadata import DataState
from app.models.realtime_market import RealtimeMarketSnapshot
from app.models.status import ConnectionState
from app.repositories.market_analysis_repository import MarketAnalysisRepository
from app.services.connection_status import get_connection_statuses
from app.services.market_regime_service import MarketRegimeService
from app.services.phase3_data_service import Phase3DataService
from app.services.realtime_market_service import (
    RealtimeMarketStore,
    realtime_market_constituents,
    refresh_realtime_stock_overlay,
    start_realtime_collector,
)
from app.utils.dates import now_kst, restore_database_kst

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


def _is_regular_market_hours(current: datetime | None = None) -> bool:
    current = current or now_kst()
    return current.weekday() < 5 and time(9, 0) <= current.time().replace(
        tzinfo=None
    ) <= time(15, 30)


def _market_view_basis(
    snapshot: RealtimeMarketSnapshot,
    *,
    current: datetime | None = None,
) -> tuple[str, bool]:
    current = current or now_kst()
    is_live = (
        snapshot.as_of_at.date() == current.date()
        and _is_regular_market_hours(current)
    )
    return ("실시간" if is_live else "마지막 거래일"), is_live


def _realtime_is_newer(
    confirmed_date: date,
    realtime_snapshot: RealtimeMarketSnapshot | None,
) -> bool:
    return (
        realtime_snapshot is not None
        and realtime_snapshot.as_of_at.date() > confirmed_date
    )


def _render_anomaly_report(
    anomalies: list[dict[str, str]],
    *,
    key: str,
) -> None:
    if not anomalies:
        return
    with st.expander(
        f"기타 · 데이터 이상 {len(anomalies)}건",
        expanded=True,
    ):
        st.warning(
            "아래 항목은 해석에 영향을 줄 수 있습니다. 정상 데이터는 이 영역에 "
            "표시하지 않습니다."
        )
        st.dataframe(
            anomalies,
            hide_index=True,
            width="stretch",
            key=key,
        )
        st.caption(
            "점검 요약: "
            + " / ".join(dict.fromkeys(item["점검 정보"] for item in anomalies))
        )


def _daily_anomalies(
    metrics: list[MarketMetricRecord],
    contributions: list[MarketContributionRecord],
) -> list[dict[str, str]]:
    anomalies: list[dict[str, str]] = []
    for metric in metrics:
        reasons: list[str] = []
        if metric.state != "AVAILABLE":
            reasons.append("값 미수집")
        if metric.collected_at is None:
            reasons.append("수집시각 없음")
        if metric.data_timing == "UNKNOWN":
            reasons.append("시세구분 확인 불가")
        if any(
            token in metric.data_quality
            for token in ("MISSING", "ERROR", "NOT_VERIFIED")
        ):
            reasons.append(f"품질 {metric.data_quality}")
        if not reasons:
            continue
        collected = (
            restore_database_kst(metric.collected_at).strftime("%Y-%m-%d %H:%M KST")
            if metric.collected_at is not None
            else "없음"
        )
        anomalies.append(
            {
                "항목": metric.metric_label,
                "이상": " · ".join(dict.fromkeys(reasons)),
                "분석 영향": "해당 지표를 국면 판단에서 제외하거나 신뢰도를 낮춤",
                "점검 정보": (
                    f"{metric.source_provider or '출처 미확인'} · {collected}"
                ),
            }
        )
    unclassified = sum(row.is_semiconductor is None for row in contributions)
    if unclassified:
        anomalies.append(
            {
                "항목": "종목 산업분류",
                "이상": f"반도체 여부 미분류 {unclassified}종목",
                "분석 영향": "반도체 기여도와 회복 신호의 정확도 저하",
                "점검 정보": "KRX 산업분류 갱신 필요",
            }
        )
    return anomalies


def _metric_map(
    metrics: list[MarketMetricRecord],
) -> dict[str, MarketMetricRecord]:
    return {metric.metric_code: metric for metric in metrics}


def _render_daily_factor_charts(
    metrics: list[MarketMetricRecord],
    *,
    basis_date: date,
    lookback_days: int,
) -> None:
    by_code = _metric_map(metrics)
    breadth_rows = []
    for code, short_label in (
        ("ADVANCING_RATIO", "상승 종목"),
        ("ABOVE_SMA20_RATIO", "20일선 상회"),
        ("ABOVE_SMA60_RATIO", "60일선 상회"),
    ):
        metric = by_code.get(code)
        if metric is not None and metric.value is not None:
            breadth_rows.append(
                {
                    "지표": short_label,
                    "비율": float(metric.value * Decimal(100)),
                }
            )

    return_rows = []
    for code, short_label in (
        ("KOSPI_RETURN", "KOSPI"),
        ("SEMICONDUCTOR_CAP_RETURN", "반도체"),
        ("DIVIDEND_RELATIVE_TO_KOSPI", "배당주 상대강도"),
    ):
        metric = by_code.get(code)
        if metric is not None and metric.value is not None:
            return_rows.append(
                {
                    "지표": short_label,
                    "수익률": float(metric.value * Decimal(100)),
                    "기간": f"{lookback_days}거래일",
                    "기준일": basis_date.isoformat(),
                    "산식": metric.calculation_method,
                }
            )

    left, right = st.columns(2)
    with left:
        st.markdown("##### 시장 폭")
        if breadth_rows:
            chart = (
                alt.Chart(alt.Data(values=breadth_rows))
                .mark_bar(cornerRadiusEnd=4)
                .encode(
                    x=alt.X(
                        "비율:Q",
                        title="종목 비율 (%)",
                        scale=alt.Scale(domain=[0, 100]),
                    ),
                    y=alt.Y("지표:N", title=None, sort=None),
                    tooltip=[
                        alt.Tooltip("지표:N"),
                        alt.Tooltip("비율:Q", format=".1f", title="비율 (%)"),
                    ],
                )
                .properties(height=145)
            )
            st.altair_chart(chart, width="stretch")
        else:
            st.info("시장 폭 계산에 필요한 값이 없습니다.")
    with right:
        st.markdown(
            f"##### {lookback_days}거래일 누적·상대수익률 "
            f"(기준일 {basis_date.isoformat()})"
        )
        if return_rows:
            maximum = max(
                1.0,
                max(abs(row["수익률"]) for row in return_rows) * 1.15,
            )
            chart = (
                alt.Chart(alt.Data(values=return_rows))
                .mark_bar(cornerRadiusEnd=4)
                .encode(
                    x=alt.X(
                        "수익률:Q",
                        title=f"{lookback_days}거래일 누적·상대수익률 (%)",
                        scale=alt.Scale(domain=[-maximum, maximum]),
                    ),
                    y=alt.Y("지표:N", title=None, sort=None),
                    color=alt.condition(
                        "datum['수익률'] >= 0",
                        alt.value("#2ca02c"),
                        alt.value("#d62728"),
                    ),
                    tooltip=[
                        alt.Tooltip("지표:N"),
                        alt.Tooltip("기간:N"),
                        alt.Tooltip("기준일:N"),
                        alt.Tooltip(
                            "수익률:Q",
                            format="+.2f",
                            title="수익률 (%)",
                        ),
                        alt.Tooltip("산식:N"),
                    ],
                )
                .properties(height=145)
            )
            st.altair_chart(chart, width="stretch")
            st.caption(
                f"KOSPI·반도체는 {lookback_days}거래일 누적수익률, "
                "배당주는 같은 기간 KOSPI 대비 상대수익률입니다. "
                "당일 하루 등락률이 아닙니다."
            )
        else:
            st.info("수익률 비교에 필요한 값이 없습니다.")


def _render_contribution_chart(
    contributions: list[MarketContributionRecord],
) -> None:
    if not contributions:
        return
    selected = sorted(
        contributions,
        key=lambda row: abs(row.contribution),
        reverse=True,
    )[:8]
    rows = [
        {
            "종목": row.name,
            "기여도": float(row.contribution * Decimal(100)),
            "수익률": float(row.return_rate * Decimal(100)),
        }
        for row in selected
    ]
    chart = (
        alt.Chart(alt.Data(values=rows))
        .mark_bar(cornerRadiusEnd=4)
        .encode(
            x=alt.X("기여도:Q", title="시장 기여도 추정 (%p)"),
            y=alt.Y(
                "종목:N",
                title=None,
                sort=alt.SortField(field="기여도", order="descending"),
            ),
            color=alt.condition(
                "datum['기여도'] >= 0",
                alt.value("#2ca02c"),
                alt.value("#d62728"),
            ),
            tooltip=[
                alt.Tooltip("종목:N"),
                alt.Tooltip("수익률:Q", format="+.2f", title="수익률 (%)"),
                alt.Tooltip("기여도:Q", format="+.3f", title="기여도 (%p)"),
            ],
        )
        .properties(height=max(190, len(rows) * 28))
    )
    contribution_date = max(row.as_of_date for row in selected)
    st.subheader(f"{contribution_date.isoformat()} 확정 일봉 기여도")
    st.altair_chart(chart, width="stretch")
    st.caption(
        "확정 시가총액 비중과 확정 일봉 수익률로 계산한 설명용 추정치이며, "
        "장중 등락과 혼용하지 않습니다."
    )


def _render_intraday_contribution_chart(
    settings: Settings,
    snapshot: RealtimeMarketSnapshot,
    *,
    is_live: bool,
) -> None:
    constituents = realtime_market_constituents(settings, limit=12)
    rows = [
        {
            "종목": item.name,
            "등락률": float(snapshot.stock_change_rates[item.symbol]),
            "기여도": float(
                item.market_weight * snapshot.stock_change_rates[item.symbol]
            ),
        }
        for item in constituents
        if item.symbol in snapshot.stock_change_rates
    ]
    rows = sorted(rows, key=lambda row: abs(row["기여도"]), reverse=True)[:8]
    snapshot_date = snapshot.as_of_at.date().isoformat()
    heading = "실시간 시장 기여도" if is_live else "마지막 거래일 시장 기여도"
    st.subheader(f"{heading} ({snapshot_date}) · 5분 잠정")
    if not rows:
        st.info(
            "상위 시가총액 종목의 실시간 체결이 아직 수신되지 않았습니다. "
            "수집기 연결 후 첫 체결부터 표시됩니다."
        )
        return
    chart = (
        alt.Chart(alt.Data(values=rows))
        .mark_bar(cornerRadiusEnd=5)
        .encode(
            x=alt.X("기여도:Q", title="KOSPI 장중 기여도 추정 (%p)"),
            y=alt.Y(
                "종목:N",
                title=None,
                sort=alt.SortField(field="기여도", order="descending"),
                axis=alt.Axis(labelLimit=150),
            ),
            color=alt.condition(
                "datum['기여도'] >= 0",
                alt.value("#2ca02c"),
                alt.value("#d62728"),
            ),
            tooltip=[
                alt.Tooltip("종목:N"),
                alt.Tooltip("등락률:Q", format="+.2f", title="장중 등락률 (%)"),
                alt.Tooltip("기여도:Q", format="+.3f", title="기여도 (%p)"),
            ],
        )
        .properties(height=max(220, len(rows) * 34))
    )
    st.altair_chart(chart, width="stretch")
    st.caption(
        "KIS 실시간 체결 등락률 × 최근 KRX 확정 시가총액 비중으로 계산합니다. "
        f"현재 수신 {len(rows)}종목 · KOSPI 지수 {snapshot.kospi_change_rate:+.2f}%"
    )


@st.fragment(run_every=300)
def _render_realtime_provisional(settings: Settings) -> None:
    store = RealtimeMarketStore(settings.realtime_market_snapshot_path)
    snapshot = store.load_snapshot()
    status = store.load_status()
    pid = store.load_pid()
    status_is_recent_live = (
        status is not None
        and status.state.value == "LIVE"
        and (now_kst() - status.updated_at).total_seconds()
        <= settings.realtime_market_interval_seconds * 2
    )
    is_running = store.process_is_alive(pid) or status_is_recent_live
    current = now_kst()
    market_is_live = False

    header_column, refresh_column, action_column = st.columns([2.4, 1, 1])
    with header_column:
        if snapshot is None:
            st.subheader("실시간 시장국면")
        else:
            basis_label, market_is_live = _market_view_basis(
                snapshot,
                current=current,
            )
            st.subheader(
                f"{basis_label} 시장국면 ({snapshot.as_of_at.date().isoformat()})"
            )
    with refresh_column:
        refresh_intraday = st.button(
            "장중자료 즉시 갱신",
            width="stretch",
            key="refresh_realtime_market_overlay",
        )
    with action_column:
        if st.button(
            "실시간 수집기 시작",
            disabled=is_running,
            width="stretch",
            key="start_realtime_market_collector",
        ):
            started, detail = start_realtime_collector(settings)
            if started:
                st.success(detail)
            else:
                st.warning(detail)

    if refresh_intraday:
        with st.spinner("KIS 상위 종목 현재가를 다시 확인하고 있습니다."):
            refreshed, refresh_errors = asyncio.run(
                refresh_realtime_stock_overlay(settings)
            )
        if refreshed is not None and refreshed.stock_change_rates:
            snapshot = refreshed
            st.success(
                f"장중 기여도 갱신 완료 · "
                f"실시간 종목 {len(refreshed.stock_change_rates)}개"
            )
        else:
            st.warning("장중 기여도 갱신에 필요한 시세를 받지 못했습니다.")
        if refresh_errors:
            st.caption("일부 미수신: " + " / ".join(refresh_errors[:3]))

    st.caption(
        "KIS KOSPI 실시간 지수·상승/하락 종목 수와 대형 반도체 2종목의 "
        "체결가를 사용합니다. 장중에는 5분마다 갱신하고, 주말·공휴일·장 마감 "
        "후에는 마지막으로 실제 체결이 수신된 거래일을 기준으로 표시합니다."
    )
    if snapshot is None:
        detail = status.detail if status is not None else "수집기 미실행"
        _render_anomaly_report(
            [
                {
                    "항목": "5분 실시간 시장국면",
                    "이상": "실시간 잠정치 없음",
                    "분석 영향": "일봉 확정 국면만 확인 가능",
                    "점검 정보": detail,
                }
            ],
            key="realtime_empty_anomalies",
        )
        return

    age_seconds = max(
        0,
        int((now_kst() - snapshot.as_of_at).total_seconds()),
    )
    if market_is_live and age_seconds <= settings.realtime_market_interval_seconds * 2:
        freshness = "실시간"
    elif market_is_live:
        freshness = "지연"
    else:
        freshness = "마지막 거래일"
    st.caption(
        f"기준 {snapshot.as_of_at.strftime('%Y-%m-%d %H:%M:%S KST')} · "
        f"5분 구간 {snapshot.bucket_started_at.strftime('%H:%M')} · "
        f"{freshness} ({age_seconds // 60}분 경과)"
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        "잠정 시장국면",
        _REGIME_LABELS.get(
            snapshot.market_regime.value,
            snapshot.market_regime.value,
        ),
    )
    col2.metric(
        "KOSPI",
        f"{snapshot.kospi_level:,.2f}",
        f"{snapshot.kospi_change_rate:+.2f}%",
    )
    col3.metric(
        "상승 종목 비율",
        f"{snapshot.advancing_ratio * Decimal(100):.1f}%",
        (f"상승 {snapshot.advancing_count} / 하락 {snapshot.declining_count}"),
    )
    col4.metric("잠정 신뢰도", f"{snapshot.confidence:.0f}/100")

    breadth_rows = [
        {
            "시장": "KOSPI",
            "구분": "상승",
            "종목 수": snapshot.advancing_count,
            "순서": 1,
        },
        {
            "시장": "KOSPI",
            "구분": "보합",
            "종목 수": snapshot.unchanged_count,
            "순서": 2,
        },
        {
            "시장": "KOSPI",
            "구분": "하락",
            "종목 수": snapshot.declining_count,
            "순서": 3,
        },
    ]
    breadth_chart = (
        alt.Chart(alt.Data(values=breadth_rows))
        .mark_bar()
        .encode(
            x=alt.X("종목 수:Q", title="KOSPI 상승·보합·하락 종목 수", stack=True),
            y=alt.Y("시장:N", axis=None, title=None),
            color=alt.Color(
                "구분:N",
                sort=["상승", "보합", "하락"],
                scale=alt.Scale(
                    domain=["상승", "보합", "하락"],
                    range=["#2ca02c", "#8c8c8c", "#d62728"],
                ),
                legend=alt.Legend(orient="top", title=None),
            ),
            order=alt.Order("순서:Q"),
            tooltip=["구분:N", alt.Tooltip("종목 수:Q", format=",")],
        )
        .properties(height=58)
    )
    st.altair_chart(breadth_chart, width="stretch")

    _render_intraday_contribution_chart(
        settings,
        snapshot,
        is_live=market_is_live,
    )

    semiconductor_rates = [
        value
        for value in (
            snapshot.samsung_change_rate,
            snapshot.sk_hynix_change_rate,
        )
        if value is not None
    ]
    semiconductor_summary = (
        " · 대형 반도체 평균 "
        f"{sum(semiconductor_rates, Decimal(0)) / len(semiconductor_rates):+.2f}%"
        if semiconductor_rates
        else ""
    )
    st.info(
        (
            f"{_REGIME_LABELS.get(snapshot.market_regime.value, snapshot.market_regime.value)}: "
            f"KOSPI {snapshot.kospi_change_rate:+.2f}%, 상승 종목 "
            f"{snapshot.advancing_ratio * Decimal(100):.1f}%"
        )
        + semiconductor_summary
    )

    anomalies: list[dict[str, str]] = []
    if market_is_live and (
        not is_running or status is None or status.state.value != "LIVE"
    ):
        anomalies.append(
            {
                "항목": "실시간 수집기",
                "이상": "수집 중단 또는 재연결 중",
                "분석 영향": "잠정 국면이 최신 시장을 반영하지 못할 수 있음",
                "점검 정보": status.detail if status is not None else "상태 없음",
            }
        )
    if freshness == "지연":
        anomalies.append(
            {
                "항목": "실시간 시세",
                "이상": f"마지막 체결 후 {age_seconds // 60}분 경과",
                "분석 영향": "마지막 정상값만 참고 가능",
                "점검 정보": "장 마감·휴장 또는 KIS 연결 확인",
            }
        )
    if market_is_live:
        missing_semiconductors = []
        if snapshot.samsung_change_rate is None:
            missing_semiconductors.append("삼성전자")
        if snapshot.sk_hynix_change_rate is None:
            missing_semiconductors.append("SK하이닉스")
        if missing_semiconductors:
            anomalies.append(
                {
                    "항목": "반도체 보조 신호",
                    "이상": f"{', '.join(missing_semiconductors)} 체결 미수신",
                    "분석 영향": "잠정 신뢰도 하락",
                    "점검 정보": "KIS 종목 체결 스트림 확인",
                }
            )
    _render_anomaly_report(anomalies, key="realtime_market_anomalies")


def render_market_dashboard(settings: Settings) -> None:
    title_column, action_column = st.columns([3, 1])
    with title_column:
        st.title("시장국면 대시보드")
    with action_column:
        refresh_requested = st.button(
            "최신 시장국면 갱신",
            type="primary",
            width="stretch",
        )
    st.caption(
        "버튼을 누르면 KIS 종목분류와 KRX 지수·종목가격을 갱신한 뒤 "
        "Phase 3 시장국면을 다시 계산합니다. 실시간 체결가가 아니라 "
        "API에서 제공되는 최신 확정 일별 데이터 기준입니다."
    )
    _render_realtime_provisional(settings)
    st.divider()
    if refresh_requested:
        refresh_date = now_kst().date()
        data_service = Phase3DataService(settings)
        regime_service = MarketRegimeService(settings)
        try:
            with st.spinner(
                "최신 KRX·KIS 데이터를 확인하고 시장국면을 다시 계산하고 있습니다."
            ):
                refresh_summary = asyncio.run(
                    data_service.refresh(as_of_date=refresh_date)
                )
                analysis = regime_service.analyze_and_store(
                    as_of_date=refresh_date,
                    as_of_at=now_kst(),
                )
            if analysis.state == DataState.AVAILABLE:
                st.success(
                    "시장국면 갱신 완료 · "
                    f"요청 기준일 {refresh_date.isoformat()} · "
                    f"시장국면 {_REGIME_LABELS.get(analysis.market_regime.value, analysis.market_regime.value)}"
                )
            else:
                missing = ", ".join(analysis.missing_core_data) or "확인 불가"
                st.warning(
                    "최신 데이터 확인은 완료했지만 시장국면 핵심 입력이 "
                    f"부족합니다. 누락: {missing}"
                )
            if refresh_summary.errors:
                st.caption(
                    "일부 공급자 응답: " + " / ".join(refresh_summary.errors[:3])
                )
        except (OSError, SQLAlchemyError, ValueError) as exc:
            st.error(f"시장국면 갱신 실패: {type(exc).__name__}")
            st.caption("데이터 연결상태와 API 이용승인 상태를 확인하세요.")
        finally:
            data_service.close()
            regime_service.close()

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

            confirmed_date = (
                max(item.as_of_date for item in contributions)
                if contributions
                else max(
                    (
                        restore_database_kst(item.as_of_at).date()
                        for item in metrics
                        if item.as_of_at is not None
                    ),
                    default=restore_database_kst(snapshot.as_of_at).date(),
                )
            )
            realtime_snapshot = RealtimeMarketStore(
                settings.realtime_market_snapshot_path
            ).load_snapshot()
            if (
                snapshot.data_state == DataState.AVAILABLE.value
                and realtime_snapshot is not None
                and _realtime_is_newer(confirmed_date, realtime_snapshot)
            ):
                st.caption(
                    "확정 일봉 Phase 3보다 최신인 시장 스냅샷을 위 화면에 "
                    "반영했습니다. "
                    f"화면 기준일 {realtime_snapshot.as_of_at.date().isoformat()}"
                )
                return
            st.subheader(
                f"최근 확정 시장국면 ({confirmed_date.isoformat()})"
            )
            st.caption(
                f"확정 시세 기준 {confirmed_date.isoformat()} · 계산 "
                + restore_database_kst(snapshot.as_of_at).strftime("%Y-%m-%d %H:%M KST")
            )
            if snapshot.data_state != "AVAILABLE":
                missing = ", ".join(snapshot.missing_core_data)
                st.warning(
                    "핵심 데이터가 부족해 시장국면을 확정할 수 없습니다. "
                    f"누락: {missing}",
                    icon="⚠️",
                )
            col1, col2, col3 = st.columns(3)
            col1.metric(
                "시장국면",
                _REGIME_LABELS.get(
                    snapshot.market_regime,
                    snapshot.market_regime,
                ),
            )
            col2.metric(
                "시장충격",
                _SHOCK_LABELS.get(
                    snapshot.shock_classification,
                    snapshot.shock_classification,
                ),
            )
            col3.metric(
                "분석 신뢰도",
                (
                    f"{snapshot.data_confidence:.0f}/100"
                    if snapshot.data_confidence is not None
                    else "계산 불가"
                ),
            )
            st.info(snapshot.explanation)

            _render_daily_factor_charts(
                metrics,
                basis_date=confirmed_date,
                lookback_days=settings.phase3_return_lookback_days,
            )

            recovery_items = (
                ("반도체 회복", snapshot.semiconductor_recovery),
                ("KOSPI 회복", snapshot.kospi_recovery),
                ("비반도체 확산", snapshot.non_semiconductor_breadth),
                (
                    "배당주 상대강도",
                    snapshot.dividend_relative_strength_recovery,
                ),
            )
            st.markdown("##### 회복 신호")
            recovery_columns = st.columns(4)
            for column, (label, value) in zip(
                recovery_columns,
                recovery_items,
                strict=True,
            ):
                column.metric(
                    label,
                    "확인" if value is True else "대기" if value is False else "미확인",
                )

            _render_contribution_chart(contributions)

            anomalies = _daily_anomalies(metrics, contributions)
            if snapshot.data_state != "AVAILABLE":
                anomalies.insert(
                    0,
                    {
                        "항목": "최근 확정 시장국면",
                        "이상": (
                            "핵심 입력 누락: "
                            + (", ".join(snapshot.missing_core_data) or "확인 불가")
                        ),
                        "분석 영향": "확정 국면 계산 보류",
                        "점검 정보": "데이터 연결상태 확인 필요",
                    },
                )
                relevant = {"KRX", "OpenDART", "한국투자증권"}
                for connection in get_connection_statuses(settings):
                    if connection.provider not in relevant:
                        continue
                    anomalies.append(
                        {
                            "항목": f"{connection.provider} 연결",
                            "이상": connection.state.value,
                            "분석 영향": "관련 입력값 수집 불가 또는 지연",
                            "점검 정보": (
                                f"{connection.provider} 연결상태: "
                                f"{connection.state.value} · {connection.detail}"
                            ),
                        }
                    )
            _render_anomaly_report(anomalies, key="daily_market_anomalies")
    finally:
        engine.dispose()
