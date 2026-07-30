from __future__ import annotations

from decimal import Decimal

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.models.backtest import BacktestResult
from app.models.metadata import DataState
from app.services.backtest_service import BacktestService
from app.services.connection_status import get_connection_statuses


def _percent(value: Decimal | None) -> str:
    return (
        "계산 불가"
        if value is None
        else f"{value * Decimal(100):.2f}%"
    )


def _render_methods(result: BacktestResult) -> None:
    st.markdown("### 데이터·계산 계약")
    rows = [
        ("사용 데이터 기간", f"{result.start_date} ~ {result.end_date}"),
        ("입력 데이터 출처", result.input_source_name),
        (
            "최근 입력 수집시각",
            (
                result.latest_input_collected_at.isoformat()
                if result.latest_input_collected_at is not None
                else "확인 불가"
            ),
        ),
        ("유니버스 구성", result.universe_construction_method),
        ("재무 가용 시점", result.financial_availability_method),
        ("정정공시 처리", result.correction_availability_method),
        ("체결가격", result.execution_price_method),
        ("수정가격 출처", result.adjusted_price_source),
        ("배당 처리", result.dividend_treatment_method),
        ("거래비용", result.transaction_cost_assumption),
        ("벤치마크", result.benchmark_method),
        ("워크포워드", result.walk_forward_method),
        ("낙폭 계산방법", result.drawdown_method),
        ("backtest_version", result.backtest_version),
        ("rule_version", result.rule_version),
        ("score_version", ", ".join(result.score_versions)),
        (
            "recommendation_rule_version",
            ", ".join(result.recommendation_rule_versions),
        ),
        ("market_rule_version", ", ".join(result.market_rule_versions)),
        ("config hash", result.config_hash),
        ("input hash", result.input_data_hash),
        ("신뢰도", result.confidence.value),
    ]
    st.dataframe(
        [{"항목": key, "내용": value} for key, value in rows],
        width="stretch",
        hide_index=True,
    )
    if result.known_survival_bias:
        st.warning(
            "알려진 생존편향·범위 한계: "
            + " / ".join(result.known_survival_bias)
        )


def _render_available(result: BacktestResult) -> None:
    metrics = result.metrics
    if metrics is None:
        return
    summary = st.columns(5)
    summary[0].metric(
        "누적 총수익률",
        _percent(metrics.cumulative_total_return),
    )
    summary[1].metric(
        "연환산수익률",
        _percent(metrics.annualized_return),
    )
    summary[2].metric(
        "벤치마크 초과",
        _percent(metrics.benchmark_excess_return),
    )
    summary[3].metric(
        "구간 종료 기준 최대낙폭",
        _percent(metrics.maximum_drawdown),
    )
    summary[4].metric(
        "평균 회전율",
        _percent(metrics.average_turnover),
    )
    st.caption(
        f"변동성 {_percent(metrics.annualized_volatility)} · "
        f"샤프 {metrics.sharpe_ratio if metrics.sharpe_ratio is not None else '계산 불가'} · "
        f"승률 {_percent(metrics.win_rate)} · "
        f"거래비용 영향 {_percent(metrics.total_transaction_cost_return)}"
    )
    if metrics.high_dividend_benchmark_excess_return is not None:
        st.caption(
            "고배당 벤치마크 초과 "
            + _percent(metrics.high_dividend_benchmark_excess_return)
        )
    st.markdown("### 추천 후 기간별 성과")
    st.dataframe(
        [
            {"기간": horizon, "평균 수익률": _percent(value)}
            for horizon, value in (
                metrics.recommendation_horizon_performance.items()
            )
        ],
        width="stretch",
        hide_index=True,
    )
    left, right = st.columns(2)
    with left:
        st.markdown("#### 시장국면별")
        st.dataframe(
            [
                {"시장국면": key, "평균 수익률": _percent(value)}
                for key, value in metrics.market_regime_performance.items()
            ],
            width="stretch",
            hide_index=True,
        )
    with right:
        st.markdown("#### 산업별")
        st.dataframe(
            [
                {"산업": key, "평균 수익률": _percent(value)}
                for key, value in metrics.industry_performance.items()
            ],
            width="stretch",
            hide_index=True,
        )
    st.markdown("### 워크포워드 구간")
    st.dataframe(
        [
            {
                "신호일": item.signal_date,
                "다음 거래 체결일": item.execution_date,
                "시점 유니버스": item.universe_count,
                "선정 종목": item.selected_count,
                "시장국면": item.market_regime,
                "회전율": _percent(item.turnover),
                "1개월 수익률": _percent(
                    item.portfolio_returns.get("1M")
                ),
                "1개월 벤치마크": _percent(
                    item.benchmark_returns.get("1M")
                ),
            }
            for item in result.folds
        ],
        width="stretch",
        hide_index=True,
    )


def render_backtest(settings: Settings) -> None:
    st.title("시점정보 기반 백테스트")
    st.write(
        "현재 종목 목록을 과거에 소급하지 않고, 시점별 유니버스·상장폐지 "
        "이력·공시 가용일·검증 수정가격이 모두 증명된 입력만 계산합니다."
    )
    st.warning(
        "데이터가 불완전하면 생존편향 제거를 주장하지 않고 "
        "백테스트 숫자 없이 누락 사유만 표시합니다.",
        icon="⚠️",
    )
    service = BacktestService(settings)
    try:
        result = service.latest()
    except (SQLAlchemyError, OSError, ValueError) as exc:
        st.error(f"백테스트 저장소 조회 실패: {type(exc).__name__}")
        return
    finally:
        service.close()
    if result is None:
        st.info("저장된 Phase 6 백테스트 실행이 없습니다.")
        st.write(
            "필요 입력: 시점별 유니버스, 상장폐지 종목과 정산값, "
            "제출일 기준 재무·정정공시 이력, 검증 수정가격, 확정 현금배당, "
            "KOSPI 벤치마크, 동일 config의 추천 스냅샷."
        )
        for item in get_connection_statuses(settings):
            if item.provider in {"KRX", "OpenDART", "한국투자증권"}:
                st.caption(
                    f"{item.provider} 연결상태: "
                    f"{item.state.value} · {item.detail}"
                )
        return
    _render_methods(result)
    if result.state != DataState.AVAILABLE:
        st.error(
            "핵심 시점정보가 부족해 성과 지표를 계산하지 않았습니다."
        )
        if result.missing_data:
            st.write("누락 데이터: " + " / ".join(result.missing_data))
        return
    _render_available(result)
