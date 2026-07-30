from __future__ import annotations

from decimal import Decimal

import streamlit as st
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.models.market_analysis import MarketRegime
from app.models.recommendation import (
    PortfolioProfile,
    RegimeAllocationTarget,
)
from app.services.recommendation_service import RecommendationService
from app.utils.dates import now_kst


def _percentage(value: Decimal) -> float:
    return float(value * Decimal(100))


def _target_inputs(
    label: str,
    target: RegimeAllocationTarget,
    *,
    key: str,
) -> RegimeAllocationTarget:
    st.markdown(f"**{label}**")
    columns = st.columns(3)
    dividend = columns[0].number_input(
        "배당주 %",
        min_value=0.0,
        max_value=100.0,
        value=_percentage(target.dividend_weight),
        step=1.0,
        key=f"{key}_dividend",
    )
    growth = columns[1].number_input(
        "성장주 %",
        min_value=0.0,
        max_value=100.0,
        value=_percentage(target.growth_weight),
        step=1.0,
        key=f"{key}_growth",
    )
    cash = columns[2].number_input(
        "현금 %",
        min_value=0.0,
        max_value=100.0,
        value=_percentage(target.cash_weight),
        step=1.0,
        key=f"{key}_cash",
    )
    return RegimeAllocationTarget(
        dividend_weight=Decimal(str(dividend)) / Decimal(100),
        growth_weight=Decimal(str(growth)) / Decimal(100),
        cash_weight=Decimal(str(cash)) / Decimal(100),
    )


def _profile_form(profile: PortfolioProfile) -> PortfolioProfile | None:
    with st.form("portfolio_settings"):
        st.markdown("### 사용자 포트폴리오 설정")
        profile_name = st.text_input(
            "설정 이름",
            value=profile.profile_name,
        )
        amounts = st.columns(3)
        total_capital = amounts[0].number_input(
            "총 투자 가능자금(KRW, 0=미설정)",
            min_value=0,
            value=int(profile.total_capital or 0),
            step=1000000,
        )
        current_cash = amounts[1].number_input(
            "현재 보유현금(KRW)",
            min_value=0,
            value=int(profile.current_cash or 0),
            step=1000000,
        )
        target_yield = amounts[2].number_input(
            "목표 배당수익률(%, 0=미설정)",
            min_value=0.0,
            max_value=100.0,
            value=float((profile.target_dividend_yield or Decimal(0)) * Decimal(100)),
            step=0.1,
        )
        limits = st.columns(4)
        target_count = limits[0].number_input(
            "목표 종목 수",
            min_value=1,
            max_value=100,
            value=profile.target_stock_count,
            step=1,
        )
        max_dividend = limits[1].number_input(
            "배당주 종목 최대 %",
            min_value=0.1,
            max_value=100.0,
            value=_percentage(profile.max_dividend_stock_weight),
            step=0.5,
        )
        max_growth = limits[2].number_input(
            "성장주 종목 최대 %",
            min_value=0.1,
            max_value=100.0,
            value=_percentage(profile.max_growth_stock_weight),
            step=0.5,
        )
        max_industry = limits[3].number_input(
            "산업 최대 %",
            min_value=0.1,
            max_value=100.0,
            value=_percentage(profile.max_industry_weight),
            step=1.0,
        )
        max_group = st.number_input(
            "동일 기업집단 최대 %",
            min_value=0.1,
            max_value=100.0,
            value=_percentage(profile.max_company_group_weight),
            step=1.0,
        )
        include_preferred = st.checkbox(
            "우선주 포함",
            value=profile.include_preferred,
        )
        include_reits = st.checkbox(
            "리츠 포함",
            value=profile.include_reits,
        )
        st.caption(
            "우선주·리츠는 Phase 2 강제필터의 공식 분류·별도 모형이 "
            "확인되지 않으면 설정과 관계없이 자동 추천되지 않습니다."
        )
        st.markdown("### 시장국면별 목표비중")
        targets = {
            MarketRegime.RED.value: _target_inputs(
                "적색 투매",
                profile.regime_targets[MarketRegime.RED.value],
                key="red",
            ),
            MarketRegime.ORANGE.value: _target_inputs(
                "주황 안정화",
                profile.regime_targets[MarketRegime.ORANGE.value],
                key="orange",
            ),
            MarketRegime.YELLOW.value: _target_inputs(
                "황색 회복",
                profile.regime_targets[MarketRegime.YELLOW.value],
                key="yellow",
            ),
            MarketRegime.GREEN.value: _target_inputs(
                "녹색 순환상승",
                profile.regime_targets[MarketRegime.GREEN.value],
                key="green",
            ),
        }
        submitted = st.form_submit_button(
            "포트폴리오 설정 저장",
            use_container_width=True,
        )
    if not submitted:
        return None
    return PortfolioProfile(
        profile_name=profile_name,
        total_capital=(Decimal(str(total_capital)) if total_capital > 0 else None),
        current_cash=Decimal(str(current_cash)),
        risk_profile=profile.risk_profile,
        target_dividend_yield=(
            Decimal(str(target_yield)) / Decimal(100) if target_yield > 0 else None
        ),
        target_stock_count=int(target_count),
        max_dividend_stock_weight=(Decimal(str(max_dividend)) / Decimal(100)),
        max_growth_stock_weight=(Decimal(str(max_growth)) / Decimal(100)),
        max_industry_weight=Decimal(str(max_industry)) / Decimal(100),
        max_company_group_weight=Decimal(str(max_group)) / Decimal(100),
        include_preferred=include_preferred,
        include_reits=include_reits,
        minimum_trading_value=profile.minimum_trading_value,
        normal_target=profile.normal_target,
        regime_targets=targets,
    )


def render_portfolio(settings: Settings) -> None:
    st.title("포트폴리오")
    st.write(
        "시장국면별 배당주·성장주·현금 목표와 종목·산업 한도를 "
        "설정합니다. 모든 판단은 읽기 전용입니다."
    )
    st.warning(
        "공식 기업집단 매핑 writer가 없어 동일 기업집단 한도는 "
        "설정·저장되지만 자동 집행 검증은 보류됩니다.",
        icon="⚠️",
    )
    service = RecommendationService(settings)
    try:
        profile = service.latest_profile()
        updated = _profile_form(profile)
        if updated is not None:
            service.save_profile(updated)
            profile = updated
            st.success("포트폴리오 설정을 새 재현성 버전으로 저장했습니다.")

        st.markdown("### 현재 보유종목 입력")
        with st.form("portfolio_position"):
            columns = st.columns(3)
            symbol = columns[0].text_input(
                "6자리 종목코드",
                max_chars=6,
            )
            quantity = columns[1].number_input(
                "보유수량",
                min_value=0.0,
                value=0.0,
                step=1.0,
            )
            average_price = columns[2].number_input(
                "평균매입가(KRW, 0=미입력)",
                min_value=0,
                value=0,
                step=100,
            )
            position_submitted = st.form_submit_button("보유종목 저장")
        if position_submitted:
            if len(symbol.strip()) != 6 or not symbol.strip().isdigit():
                st.error("종목코드는 6자리 숫자여야 합니다.")
            elif quantity <= 0:
                st.error("보유수량은 0보다 커야 합니다.")
            else:
                saved = service.save_position(
                    symbol=symbol.strip(),
                    quantity=Decimal(str(quantity)),
                    average_purchase_price=(
                        Decimal(str(average_price)) if average_price > 0 else None
                    ),
                    as_of_at=now_kst(),
                )
                if saved:
                    st.success("사용자 입력 보유종목을 저장했습니다.")
                else:
                    st.error("저장된 실제 종목 또는 포트폴리오 설정을 찾지 못했습니다.")

        positions = service.positions()
        latest = service.latest()
        by_symbol = (
            {item.symbol: item for item in latest.recommendations}
            if latest is not None
            else {}
        )
        st.markdown("### 보유·매도 재검토 판단")
        if not positions:
            st.info("사용자가 입력한 보유종목이 없습니다.")
        else:
            position_rows: list[dict[str, object]] = []
            for position in positions:
                symbol_value = str(position["symbol"])
                recommendation = by_symbol.get(symbol_value)
                position_rows.append(
                    {
                        **position,
                        "판정": (
                            recommendation.category_label
                            if recommendation is not None
                            else "추천 실행 데이터 없음"
                        ),
                        "보유·매도 판단": (
                            position["holding_action"]
                        ),
                        "근거": position["holding_reason"],
                    }
                )
            st.dataframe(
                position_rows,
                use_container_width=True,
            )
        st.caption(
            "RSI 하나만으로 전량매도를 지시하지 않습니다. "
            "즉시 재검토는 자동 매도 주문이 아니라 위험 확인 상태입니다."
        )

        st.markdown("### 최신 목표 포트폴리오")
        allocated = (
            [
                item
                for item in latest.recommendations
                if item.target_weight is not None and item.target_weight > 0
            ]
            if latest is not None
            else []
        )
        if not allocated:
            st.info("시장국면·점수·공식 산업분류를 모두 충족한 목표배분이 없습니다.")
        else:
            allocation_rows: list[dict[str, object]] = []
            for item in allocated:
                target_weight = item.target_weight
                if target_weight is None:
                    continue
                allocation_rows.append(
                    {
                        "종목명": item.name,
                        "종목코드": item.symbol,
                        "그룹": item.category_label,
                        "전략군": item.sleeve.value,
                        "산업": item.industry_code,
                        "목표비중": f"{target_weight * Decimal(100):.2f}%",
                        "1차 조건부 비중": (
                            f"{(item.initial_buy_weight or Decimal(0)) * Decimal(100):.2f}%"
                        ),
                        "기업집단 확인": item.company_group_check_state,
                    }
                )
            st.dataframe(
                allocation_rows,
                use_container_width=True,
            )
    except (SQLAlchemyError, OSError, ValueError, ValidationError) as exc:
        st.error(
            f"포트폴리오 화면을 완료하지 못했습니다. 오류 유형: {type(exc).__name__}"
        )
    finally:
        service.close()
