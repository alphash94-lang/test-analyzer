from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal

import streamlit as st
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.models.recommendation import (
    RecommendationDecision,
    RecommendationRunResult,
)
from app.services.connection_status import get_connection_statuses
from app.services.recommendation_service import RecommendationService
from app.utils.dates import SEOUL, now_kst


def _score(value: Decimal | None) -> str:
    return "계산 불가" if value is None else f"{value}/100"


def _weight(value: Decimal | None) -> str:
    return "산정 불가" if value is None else f"{value * Decimal(100):.2f}%"


def _result_rows(result: RecommendationRunResult) -> list[dict[str, object]]:
    return [
        {
            "순위": index,
            "종목명": item.name,
            "종목코드": item.symbol,
            "판정": item.category_label,
            "Phase 2 핵심점수": _score(item.investment_score),
            "진입준비(수급 제외)": _score(item.entry_score),
            "데이터 신뢰도": _score(item.data_confidence),
            "시장국면": item.market_regime.value,
            "목표비중": _weight(item.target_weight),
            "1차 검토비중": _weight(item.initial_buy_weight),
            "추천 근거": (
                item.positive_reasons[0]
                if item.positive_reasons
                else "확인된 긍정 근거 없음"
            ),
            "위험·제외 근거": (
                item.exclusion_reasons[0]
                if item.exclusion_reasons
                else item.risk_reasons[0]
                if item.risk_reasons
                else "추가 위험 근거 없음"
            ),
        }
        for index, item in enumerate(result.recommendations, start=1)
    ]


def _render_decision(item: RecommendationDecision) -> None:
    st.subheader(f"{item.name} ({item.symbol})")
    columns = st.columns(4)
    columns[0].metric("판정", item.category_label)
    columns[1].metric("Phase 2 핵심점수", _score(item.investment_score))
    columns[2].metric("진입준비", _score(item.entry_score))
    columns[3].metric("데이터 신뢰도", _score(item.data_confidence))
    st.caption(
        f"점수 범위: {item.score_scope} · 진입 범위: "
        f"{item.entry_score_scope} · 시장국면: {item.market_regime.value}"
    )
    positive, risk = st.columns(2)
    with positive:
        st.markdown("#### 긍정 근거")
        if item.positive_reasons:
            for reason in item.positive_reasons:
                st.write(f"- {reason}")
        else:
            st.info("확인된 긍정 근거가 없습니다.")
    with risk:
        st.markdown("#### 반대·위험 근거")
        reasons = (*item.risk_reasons, *item.exclusion_reasons)
        if reasons:
            for reason in reasons:
                st.write(f"- {reason}")
        else:
            st.info("추가 위험 근거가 저장되지 않았습니다.")
    if item.missing_data:
        st.warning("누락된 핵심 데이터: " + ", ".join(item.missing_data))
    st.markdown("#### 강제필터")
    st.dataframe(list(item.filter_results), use_container_width=True)
    plan = item.split_buy_plan
    st.markdown("#### 분할매수 검토안")
    if plan is None or not plan.tranches:
        st.info(
            plan.explanation
            if plan is not None
            else "분할매수 계획이 저장되지 않았습니다."
        )
    else:
        if plan.reference_price is not None:
            st.write(
                f"기준가격: {plan.reference_price} "
                f"{plan.reference_price_currency or '단위 확인 필요'} · "
                f"{plan.reference_price_date} · "
                f"{plan.reference_price_provider or '출처 확인 필요'} · "
                f"수집 {plan.reference_price_collected_at or '확인 필요'} · "
                f"시점 {(
                    plan.reference_price_timing.value
                    if plan.reference_price_timing is not None
                    else '확인 필요'
                )}"
            )
        else:
            st.warning(
                "검증된 수정종가가 없어 기준가격과 회차별 목표가격을 표시하지 않습니다."
            )
        st.dataframe(
            [
                {
                    "회차": tranche.sequence,
                    "목표 편입액 내 비중": (
                        f"{tranche.fraction_of_target * Decimal(100):.0f}%"
                    ),
                    "포트폴리오 비중": _weight(tranche.portfolio_weight),
                    "목표가격": (
                        str(tranche.target_price)
                        if tranche.target_price is not None
                        else "산정 안 함"
                    ),
                    "현재 조건부 검토": ("가능" if tranche.eligible_now else "대기"),
                    "실행 조건": " / ".join(tranche.execution_conditions),
                }
                for tranche in plan.tranches
            ],
            use_container_width=True,
        )
        st.error(
            "취소 조건: " + " / ".join(plan.cancellation_conditions),
            icon="🛑",
        )
        st.caption(plan.explanation)
    with st.expander("저장된 원시 지표·재현성 메타데이터"):
        st.json(item.raw_metrics)


def _render_result(result: RecommendationRunResult) -> None:
    st.markdown("### 최신 추천 실행")
    st.caption(
        f"분석시각 {result.analyzed_at.strftime('%Y-%m-%d %H:%M:%S KST')} · "
        f"데이터 기준일 {result.basis_date} · "
        f"score_version {result.score_version} · "
        f"rule_version {result.rule_version} · "
        f"market_rule_version {result.market_rule_version}"
    )
    st.caption(
        f"config hash {result.config_hash} · input hash {result.input_data_hash}"
    )
    summary = st.columns(5)
    summary[0].metric("분석 종목", result.total_count)
    summary[1].metric("검토 그룹", result.recommended_count)
    summary[2].metric("투자배제", result.excluded_count)
    summary[3].metric("데이터 부족", result.insufficient_count)
    summary[4].metric("시장국면", result.market_regime.value)
    if result.missing_core_data:
        st.warning("추천 실행 핵심 입력 부족: " + ", ".join(result.missing_core_data))
    if not result.recommendations:
        st.warning(
            "실제 KOSPI 유니버스가 저장되어 있지 않아 추천 결과가 없습니다. "
            "예시 종목이나 가짜 점수를 표시하지 않습니다."
        )
        return
    st.dataframe(_result_rows(result), use_container_width=True)
    choices = {
        f"{item.category_label} · {item.name} ({item.symbol})": item
        for item in result.recommendations
    }
    selected = st.selectbox(
        "종목별 근거·분할매수 조건 확인",
        tuple(choices),
    )
    _render_decision(choices[selected])


def render_recommendations(settings: Settings) -> None:
    st.title("추천종목")
    st.write(
        "저장된 실제 KOSPI 유니버스 전체에 강제필터를 먼저 적용하고, "
        "통과 종목만 Phase 2 점수·Phase 3 시장국면·투자한도로 분류합니다."
    )
    st.warning(
        "읽기 전용 분석입니다. 자동주문, 주문 API, 계좌이체를 실행하지 않습니다.",
        icon="🔒",
    )
    service = RecommendationService(settings)
    try:
        latest = service.latest()
        profile = service.latest_profile()
        st.caption(
            f"포트폴리오 설정: 종목 수 {profile.target_stock_count}, "
            f"산업 최대 {profile.max_industry_weight * Decimal(100):.1f}%, "
            f"기업집단 최대 {profile.max_company_group_weight * Decimal(100):.1f}%"
        )
        as_of_date = st.date_input(
            "분석 기준일",
            value=now_kst().date(),
            max_value=now_kst().date(),
        )
        if st.button("추천하기", type="primary", use_container_width=True):
            progress_bar = st.progress(0.0)
            status = st.empty()

            def update_progress(
                processed: int,
                total: int,
                symbol: str,
                category: str,
            ) -> None:
                fraction = processed / total if total else 1.0
                progress_bar.progress(
                    fraction,
                    text=f"{processed}/{total} · {symbol} · {category}",
                )
                status.caption("전체 유니버스 강제필터·점수·시장국면 결합 중")

            requested_at = min(
                datetime.combine(as_of_date, time.max, tzinfo=SEOUL),
                now_kst(),
            )
            latest = service.run_universe(
                as_of_at=requested_at,
                profile=profile,
                progress=update_progress,
            )
            progress_bar.progress(1.0, text="분석 및 저장 완료")
            status.caption("동일 입력·config 재실행 시 저장 결과를 재사용합니다.")
        if latest is None:
            st.info("저장된 Phase 4 추천 실행이 없습니다.")
            for item in get_connection_statuses(settings):
                if item.provider in {
                    "KRX",
                    "OpenDART",
                    "한국투자증권",
                }:
                    st.caption(
                        f"{item.provider} 연결상태: {item.state.value} · {item.detail}"
                    )
            st.warning(
                "추천하기를 실행해도 핵심 공식 데이터가 없으면 "
                "가짜 추천 대신 데이터 부족 사유만 저장됩니다."
            )
        else:
            _render_result(latest)
    except (SQLAlchemyError, OSError, ValueError, ValidationError) as exc:
        st.error(f"추천 실행을 완료하지 못했습니다. 오류 유형: {type(exc).__name__}")
    finally:
        service.close()
