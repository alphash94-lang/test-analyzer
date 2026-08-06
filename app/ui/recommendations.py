from __future__ import annotations

import asyncio
from datetime import datetime, time
from decimal import Decimal

import streamlit as st
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.models.recommendation import (
    RecommendationCategory,
    RecommendationDecision,
    RecommendationRunResult,
)
from app.services.event_service import EventService
from app.services.integrated_recommendation_service import (
    INTEGRATED_RULE_VERSION,
    LIQUID_QUALITY_RULE_VERSION,
    LIQUIDITY_POOL_MAX_RANK,
    IntegratedRecommendation,
    IntegratedRecommendationService,
)
from app.services.recommendation_job import recommendation_jobs
from app.services.recommendation_service import RecommendationService
from app.services.stock_analysis_service import StockAnalysisService
from app.ui.connection_status import cached_connection_statuses
from app.utils.dates import SEOUL, now_kst

_MARKET_REGIME_LABELS = {
    "RED": "적색 · 투매",
    "ORANGE": "주황 · 안정화",
    "YELLOW": "황색 · 회복",
    "GREEN": "녹색 · 순환상승",
    "UNCERTAIN": "혼조 · 중립",
}

_RECOMMENDATION_CATEGORIES = {
    "financial": (
        "1. 재무적 추천",
        "가치·실적·재무 안정성을 중심으로 선별합니다.",
    ),
    "integrated": (
        "2. 재무적 + 비재무적 추천",
        "재무점수에 최근 뉴스와 공식 공시 신호를 결합합니다.",
    ),
    "liquid_quality": (
        "3. 거래대금 우량주 추천",
        "거래대금 100위 안에서 재무·뉴스·공시가 함께 좋은 5종목을 찾습니다.",
    ),
}


def _open_stock_detail(item: RecommendationDecision) -> None:
    st.session_state["stock_detail_origin"] = "추천종목"
    st.session_state["stock_detail_recommendation"] = item.model_dump(mode="json")
    st.session_state["stock_search_query"] = item.symbol
    st.session_state["main_menu"] = "개별 종목 검색"


def _category_detail_decision(
    item: RecommendationDecision,
    *,
    category_label: str,
    score_label: str,
    score: Decimal,
    status_label: str,
    integrated: IntegratedRecommendation,
) -> RecommendationDecision:
    """Attach the selected category's independent result to stock detail."""
    raw_metrics = dict(item.raw_metrics)
    raw_metrics.update(
        {
            "detail_category_label": category_label,
            "detail_score_label": score_label,
            "detail_score": str(score),
            "detail_status_label": status_label,
            "detail_news_article_count": integrated.news_article_count,
            "detail_disclosure_count": integrated.disclosure_count,
            "detail_event_evidences": [
                {
                    "title": evidence.title,
                    "source_kind": evidence.source_kind,
                    "sentiment": evidence.sentiment,
                    "published_date": evidence.published_date.isoformat(),
                    "rationale": evidence.rationale,
                    "contribution": str(evidence.contribution),
                    "source_url": evidence.source_url,
                }
                for evidence in integrated.evidences
            ],
            "detail_news_evidences": [
                {
                    "title": news.title,
                    "summary": news.summary,
                    "published_date": news.published_date.isoformat(),
                    "sentiment": news.sentiment,
                    "rationale": news.rationale,
                    "source_url": news.source_url,
                }
                for news in integrated.news_evidences
            ],
        }
    )
    return item.model_copy(
        update={
            "category_label": category_label,
            "raw_metrics": raw_metrics,
        }
    )


def _score(value: Decimal | None) -> str:
    return "0/100" if value is None else f"{value}/100"


def _weight(value: Decimal | None) -> str:
    return "비선정(0%)" if value is None else f"{value * Decimal(100):.2f}%"


def _trading_value(value: Decimal) -> str:
    if value >= Decimal(100_000_000):
        return f"{value / Decimal(100_000_000):,.1f}억원"
    return f"{value / Decimal(10_000):,.0f}만원"


def _render_news_disclosure_evidence(item: IntegratedRecommendation) -> None:
    """Render only stored provider text and rule-based directions."""
    positive_signals = tuple(
        evidence
        for evidence in item.evidences
        if evidence.sentiment == "POSITIVE"
    )
    negative_signals = tuple(
        evidence
        for evidence in item.evidences
        if evidence.sentiment == "NEGATIVE"
    )
    st.markdown("**뉴스·공시 호재·악재 요약**")
    st.caption("최근 90일의 네이버 뉴스와 공식 공시를 구조화 규칙으로 판정했습니다.")
    good_column, bad_column = st.columns(2)
    with good_column:
        st.markdown(f"##### 호재 {len(positive_signals)}건")
        if positive_signals:
            for evidence in positive_signals:
                source = "네이버 뉴스" if evidence.source_kind == "NEWS" else "공시"
                st.markdown(
                    f"- {evidence.published_date} · {source} · {evidence.title}"
                )
        else:
            st.caption("확인된 호재 신호가 없습니다.")
    with bad_column:
        st.markdown(f"##### 악재 {len(negative_signals)}건")
        if negative_signals:
            for evidence in negative_signals:
                source = "네이버 뉴스" if evidence.source_kind == "NEWS" else "공시"
                st.markdown(
                    f"- {evidence.published_date} · {source} · {evidence.title}"
                )
        else:
            st.caption("확인된 악재 신호가 없습니다.")

    with st.expander("주요 뉴스·공시 원문 상세"):
        st.markdown("##### 네이버 주요 뉴스 요약")
        st.caption(
            "최근 90일 네이버 뉴스 검색 API의 제목·제공 요약을 최신순으로 "
            "최대 5건 표시합니다. 기사 본문을 추정하거나 생성하지 않습니다."
        )
        if item.news_evidences:
            for index, news in enumerate(item.news_evidences, start=1):
                direction = (
                    "호재"
                    if news.sentiment == "POSITIVE"
                    else "악재"
                    if news.sentiment == "NEGATIVE"
                    else "중립·미분류"
                )
                st.markdown(
                    f"**{news.published_date} · {direction} · {news.title}**"
                )
                st.write(news.summary)
                st.link_button(
                    "기사 원문 보기",
                    news.source_url,
                    key=f"news-evidence-{item.decision.symbol}-{index}",
                    width="content",
                )

        else:
            st.info(
                "저장된 네이버 뉴스 제목·요약이 없습니다. 상세자료 갱신 후 "
                "실제 수집 결과가 있을 때만 요약과 호재·악재를 표시합니다."
            )

        disclosures = tuple(
            evidence
            for evidence in item.evidences
            if evidence.source_kind == "DISCLOSURE"
        )
        st.markdown("##### 공식 공시 근거")
        if disclosures:
            for evidence in disclosures:
                direction = (
                    "호재"
                    if evidence.sentiment == "POSITIVE"
                    else "악재"
                    if evidence.sentiment == "NEGATIVE"
                    else "중립·미분류"
                )
                st.markdown(
                    f"- {evidence.published_date} · {direction} "
                    f"({evidence.contribution:+}점) · {evidence.title}"
                )
                st.caption(evidence.rationale)
        else:
            st.caption("점수 근거로 분류된 공식 공시가 없습니다.")


def _select_recommendation_category(category: str | None) -> None:
    if category is None:
        st.session_state.pop("recommendation_category", None)
    else:
        st.session_state["recommendation_category"] = category


def _render_category_selector() -> str | None:
    selected = st.session_state.get("recommendation_category")
    if selected in _RECOMMENDATION_CATEGORIES:
        title, description = _RECOMMENDATION_CATEGORIES[selected]
        st.button(
            "← 추천 카테고리 선택",
            key="recommendation-category-back",
            on_click=_select_recommendation_category,
            args=(None,),
        )
        st.markdown(f"## {title}")
        st.caption(description)
        return selected

    st.markdown("## 어떤 기준으로 볼까요?")
    columns = st.columns(3)
    for column, (key, (title, description)) in zip(
        columns,
        _RECOMMENDATION_CATEGORIES.items(),
        strict=True,
    ):
        with column, st.container(border=True):
            st.markdown(f"### {title}")
            st.write(description)
            st.button(
                "추천 순위 보기 →",
                key=f"open-recommendation-category-{key}",
                type="primary",
                width="stretch",
                on_click=_select_recommendation_category,
                args=(key,),
            )
    return None


def _entry_readiness_label(
    value: Decimal | None,
    threshold: Decimal,
) -> str:
    if value is None:
        return "계산 불가"
    return "진입 검토 가능" if value >= threshold else "대기"


def _sorted_decisions(
    decisions: tuple[RecommendationDecision, ...],
    *,
    entry_threshold: Decimal | None = None,
) -> tuple[RecommendationDecision, ...]:
    return tuple(
        sorted(
            decisions,
            key=lambda item: (
                item.investment_score or Decimal(0),
                item.entry_score or Decimal(0),
                item.data_confidence or Decimal(0),
            ),
            reverse=True,
        )
    )


def _result_rows(
    decisions: tuple[RecommendationDecision, ...],
    *,
    entry_threshold: Decimal,
) -> list[dict[str, object]]:
    return [
        {
            "순위": index,
            "종목명": item.name,
            "종목코드": item.symbol,
            "판정": item.category_label,
            "저평가 매력점수": _score(item.investment_score),
            f"진입준비도 (권장 {entry_threshold}점↑)": _score(item.entry_score),
            "진입 판단": _entry_readiness_label(
                item.entry_score,
                entry_threshold,
            ),
            "데이터 신뢰도": _score(item.data_confidence),
            "시장국면": _MARKET_REGIME_LABELS.get(
                item.market_regime.value,
                item.market_regime.value,
            ),
            "목표비중": _weight(item.target_weight),
            "핵심 추천 근거": (
                item.positive_reasons[0]
                if item.positive_reasons
                else "확인된 긍정 근거 없음"
            ),
            "주요 위험": (
                item.exclusion_reasons[0]
                if item.exclusion_reasons
                else item.risk_reasons[0]
                if item.risk_reasons
                else "추가 위험 근거 없음"
            ),
        }
        for index, item in enumerate(
            _sorted_decisions(
                decisions,
                entry_threshold=entry_threshold,
            ),
            start=1,
        )
    ]


def _render_top_recommendations(
    decisions: tuple[RecommendationDecision, ...],
    *,
    entry_threshold: Decimal,
) -> None:
    st.subheader("추천 상위 5종목")
    st.caption(
        f"진입준비도 {entry_threshold}점 이상이면 ‘진입 검토 가능’, "
        "미만이면 ‘대기’입니다. 종목명을 누르면 차트와 상세 분석으로 이동합니다."
    )
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for rank, item in enumerate(decisions[:5], start=1):
        with st.container(border=True):
            st.button(
                f"{medals.get(rank, '•')} {rank}위 · {item.name} ({item.symbol})  →",
                key=f"open-recommendation-stock-{item.symbol}",
                type="primary" if rank == 1 else "secondary",
                width="stretch",
                on_click=_open_stock_detail,
                args=(item,),
            )
            st.caption(
                f"{item.category_label} · "
                f"{_MARKET_REGIME_LABELS.get(item.market_regime.value, item.market_regime.value)}"
            )
            columns = st.columns(4)
            columns[0].metric(
                "저평가 매력",
                _score(item.investment_score),
            )
            columns[1].metric(
                f"진입 판단 ({entry_threshold}점↑)",
                _entry_readiness_label(
                    item.entry_score,
                    entry_threshold,
                ),
                _score(item.entry_score),
                delta_color="off",
            )
            columns[2].metric(
                "데이터 신뢰도",
                _score(item.data_confidence),
            )
            columns[3].metric(
                "목표비중",
                _weight(item.target_weight),
            )
            positive_notes = item.positive_reasons[:2]
            st.markdown(
                "**선정 근거 주석**  \n"
                + (
                    " · ".join(positive_notes)
                    if positive_notes
                    else "현재 확인된 강제 제외 사유가 없고 종합점수가 상위권입니다."
                )
            )
            caution = (
                item.exclusion_reasons[0]
                if item.exclusion_reasons
                else item.risk_reasons[0]
                if item.risk_reasons
                else "추가로 확인된 주요 위험 없음"
            )
            st.caption(f"주의: {caution}")


def _render_decision(
    item: RecommendationDecision,
    *,
    entry_threshold: Decimal,
) -> None:
    st.subheader(f"종목별 상세 분석 · {item.name} ({item.symbol})")
    columns = st.columns(5)
    columns[0].metric("판정", item.category_label)
    columns[1].metric("저평가 매력점수", _score(item.investment_score))
    columns[2].metric(
        f"진입 판단 ({entry_threshold}점↑)",
        _entry_readiness_label(item.entry_score, entry_threshold),
        _score(item.entry_score),
        delta_color="off",
    )
    columns[3].metric("데이터 신뢰도", _score(item.data_confidence))
    columns[4].metric("목표비중", _weight(item.target_weight))
    st.caption(
        "시장국면: "
        + _MARKET_REGIME_LABELS.get(
            item.market_regime.value,
            item.market_regime.value,
        )
    )

    positive, risk = st.columns(2)
    with positive:
        st.markdown("#### 추천 근거")
        for reason in item.positive_reasons or ("확인된 긍정 근거가 없습니다.",):
            st.write(f"- {reason}")
    with risk:
        st.markdown("#### 위험·제외 근거")
        reasons = (*item.risk_reasons, *item.exclusion_reasons)
        for reason in reasons or ("추가 위험 근거가 없습니다.",):
            st.write(f"- {reason}")

    if item.missing_data:
        st.warning("추가 확인 데이터: " + ", ".join(item.missing_data))

    with st.expander("상세 설명 · 계산 근거와 필터"):
        st.caption(
            f"점수 범위: {item.score_scope} · 진입 범위: {item.entry_score_scope}"
        )
        components = item.raw_metrics.get("score_components", [])
        if components:
            st.markdown("##### 점수 구성요소")
            st.dataframe(components, width="stretch")
        st.markdown("##### 강제 필터 결과")
        st.dataframe(list(item.filter_results), width="stretch")
        st.markdown("##### 원자료")
        st.json(item.raw_metrics)

    plan = item.split_buy_plan
    with st.expander("분할매수 검토안"):
        if plan is None:
            st.info("분할매수 검토안이 저장되지 않았습니다.")
        elif not plan.tranches:
            st.info(plan.explanation)
        else:
            st.dataframe(
                [
                    {
                        "회차": tranche.sequence,
                        "목표 편입액 대비": (
                            f"{tranche.fraction_of_target * Decimal(100):.0f}%"
                        ),
                        "포트폴리오 비중": _weight(tranche.portfolio_weight),
                        "현재 조건부 검토": (
                            "가능" if tranche.eligible_now else "대기"
                        ),
                        "조건": " / ".join(tranche.execution_conditions),
                    }
                    for tranche in plan.tranches
                ],
                width="stretch",
            )
            st.caption(plan.explanation)


def _render_result(
    result: RecommendationRunResult,
    *,
    entry_threshold: Decimal,
) -> None:
    st.markdown("### 최신 추천 실행 · KOSPI 전체 분석 결과")
    st.caption(f"데이터 기준일 {result.basis_date} · 총 {result.total_count}종목 분석")
    summary = st.columns(4)
    summary[0].metric("검토 후보", result.recommended_count)
    summary[1].metric("기준 미달·필터 제외", result.excluded_count)
    summary[2].metric("점수 계산 불가", result.insufficient_count)
    summary[3].metric(
        "시장국면",
        _MARKET_REGIME_LABELS.get(
            result.market_regime.value,
            result.market_regime.value,
        ),
    )

    if result.missing_core_data:
        st.warning("실행 핵심 입력 부족: " + ", ".join(result.missing_core_data))
    if not result.recommendations:
        st.warning(
            "실제 KOSPI 유니버스가 저장되어 있지 않아 분석할 상장 보통주가 없습니다."
        )
        return

    candidates = tuple(
        item
        for item in result.recommendations
        if item.category
        not in {
            RecommendationCategory.EXCLUDED,
            RecommendationCategory.INSUFFICIENT_DATA,
        }
    )
    candidates = _sorted_decisions(
        candidates,
        entry_threshold=entry_threshold,
    )
    if not candidates:
        st.warning(
            "현재 검토 기준을 통과한 종목이 없습니다. "
            "상세 설명에서 전체 점수와 제외 이유를 확인할 수 있습니다."
        )
        return

    _render_top_recommendations(
        candidates,
        entry_threshold=entry_threshold,
    )

    with st.expander("상세 설명 · 전체 후보와 제외 종목"):
        show_all = st.checkbox(
            "기준 미달·필터 제외 종목도 함께 보기",
            value=False,
            help=(
                "체크하면 점수가 낮거나 실제 강제 필터에서 제외된 종목까지 "
                "전체 순위로 확인합니다."
            ),
        )
        visible = result.recommendations if show_all else candidates
        visible = _sorted_decisions(
            visible,
            entry_threshold=entry_threshold,
        )
        table_state = st.dataframe(
            _result_rows(visible, entry_threshold=entry_threshold),
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="recommendation-result-table",
        )
        st.caption(
            "종목 행을 클릭하면 해당 종목의 차트·재무·추천근거 화면으로 이동합니다."
        )
        selection_state = table_state.get("selection", {})
        selected_rows = selection_state.get("rows", [])
        if selected_rows:
            selected_index = selected_rows[0]
            if 0 <= selected_index < len(visible):
                selected_item = visible[selected_index]
                consumed_symbol = st.session_state.get("recommendation-row-consumed")
                if consumed_symbol != selected_item.symbol:
                    st.session_state["recommendation-row-consumed"] = (
                        selected_item.symbol
                    )
                    _open_stock_detail(selected_item)
                    st.rerun()
        else:
            st.session_state.pop("recommendation-row-consumed", None)
        st.caption(
            f"분석시각 {result.analyzed_at.strftime('%Y-%m-%d %H:%M:%S KST')} · "
            f"score {result.score_version} · rule {result.rule_version}"
        )

    choices = {
        f"{index}위 · {item.name} ({item.symbol}) · {item.investment_score}/100": item
        for index, item in enumerate(candidates, start=1)
    }
    selected = st.selectbox(
        "상세 화면으로 이동할 종목",
        tuple(choices),
        key="recommendation-detail-choice",
    )
    st.button(
        "선택 종목 상세 차트·추천근거 보기 →",
        type="primary",
        width="stretch",
        on_click=_open_stock_detail,
        args=(choices[selected],),
    )


def _render_integrated_recommendations(
    result: RecommendationRunResult,
    *,
    settings: Settings,
    entry_threshold: Decimal,
) -> None:
    candidates = _sorted_decisions(
        tuple(
            item
            for item in result.recommendations
            if item.category
            not in {
                RecommendationCategory.EXCLUDED,
                RecommendationCategory.INSUFFICIENT_DATA,
            }
        ),
        entry_threshold=entry_threshold,
    )
    if not candidates:
        return

    st.markdown("---")
    st.markdown("### 재무 + 뉴스·공시 종합 추천")
    st.write(
        "가치·시장점수와 최신 실적 추세를 합친 재무점수 70%, "
        "최근 90일 뉴스·공시 신호 30%를 "
        "결합한 별도 순위입니다. 부정 신호는 긍정보다 크게 감점하고, "
        "부도·상장폐지·감사 위험 등 중대 공시는 종합 추천에서 제외합니다."
    )
    st.caption(
        "뉴스는 제목과 제공 요약, 공시는 공식 제목에 확인되는 구조화 규칙만 "
        "사용합니다. 비재무 자료가 없는 종목에는 중립점수를 임의 부여하지 않습니다."
    )

    refresh_candidates = candidates[:5]
    refresh_requested = st.button(
        "재무 상위 5종목 종합자료 갱신",
        key="refresh-integrated-recommendation-events",
        help="현재 재무 추천 상위 후보의 부족한 재무와 DART 공시·네이버 뉴스를 갱신합니다.",
    )
    if refresh_requested:
        progress = st.progress(0.0)
        status = st.empty()
        event_service = EventService(settings)
        analysis_service = StockAnalysisService(settings)
        refresh_errors: list[str] = []
        try:
            for index, item in enumerate(refresh_candidates, start=1):
                status.caption(
                    f"{index}/{len(refresh_candidates)} · {item.name} 재무·뉴스·공시 확인 중"
                )
                snapshot = analysis_service.snapshot(item.symbol)
                financial_years = {
                    row.business_year
                    for row in (
                        snapshot.financial_history if snapshot is not None else ()
                    )
                    if row.value is not None
                }
                if len(financial_years) < 3:
                    financial_summary = asyncio.run(
                        analysis_service.refresh(
                            symbol=item.symbol,
                            as_of_date=result.basis_date,
                            years=3,
                            incremental=True,
                        )
                    )
                    refresh_errors.extend(financial_summary.errors)
                summary = asyncio.run(
                    event_service.refresh(
                        symbol=item.symbol,
                        as_of_date=result.basis_date,
                        events_only=True,
                    )
                )
                refresh_errors.extend(summary.errors)
                progress.progress(index / len(refresh_candidates))
        finally:
            event_service.close()
            analysis_service.close()
        status.caption("종합 추천용 재무·뉴스·공시 갱신 완료")
        if refresh_errors:
            st.warning(
                "일부 공급자 응답을 받지 못했습니다: "
                + " / ".join(dict.fromkeys(refresh_errors[:3]))
            )

    integrated_service = IntegratedRecommendationService(settings)
    try:
        integrated = integrated_service.build(
            result.recommendations,
            basis_date=result.basis_date,
        )
    finally:
        integrated_service.close()

    eligible = tuple(item for item in integrated if item.eligible)
    severe_count = sum(
        item.status_label == "중대 위험 공시로 제외" for item in integrated
    )
    missing_financial_count = sum(
        item.status_label == "최신 실적 추세 미확인" for item in integrated
    )
    coverage_columns = st.columns(4)
    coverage_columns[0].metric("비재무 자료 확인", f"{len(integrated)}종목")
    coverage_columns[1].metric("종합 추천 가능", f"{len(eligible)}종목")
    coverage_columns[2].metric("중대 위험 제외", f"{severe_count}종목")
    coverage_columns[3].metric("실적 추세 미확인", f"{missing_financial_count}종목")
    if not integrated:
        st.info(
            "현재 재무 후보에 저장된 최근 뉴스·공시가 없습니다. "
            "위 갱신 버튼으로 상위 5종목의 비재무 자료를 수집할 수 있습니다."
        )
        return
    if not eligible:
        st.warning("뉴스·공시가 확인된 후보가 모두 중대 위험 기준에 걸렸습니다.")
        return

    top = eligible[:5]
    st.subheader("추천 상위 5종목")
    st.caption("모든 추천 카테고리는 같은 카드 구성으로 점수·근거·위험을 비교합니다.")
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for index, item in enumerate(top, start=1):
        detail_decision = _category_detail_decision(
            item.decision,
            category_label=f"재무+비재무 추천 {index}위",
            score_label="재무+비재무 종합점수",
            score=item.combined_score,
            status_label=item.status_label,
            integrated=item,
        )
        with st.container(border=True):
            st.button(
                f"{medals.get(index, '•')} {index}위 · "
                f"{item.decision.name} ({item.decision.symbol})  →",
                key=f"integrated-detail-{item.decision.symbol}",
                type="primary" if index == 1 else "secondary",
                width="stretch",
                on_click=_open_stock_detail,
                args=(detail_decision,),
            )
            st.caption(f"{item.status_label} · {item.coverage_label}")
            columns = st.columns(4)
            columns[0].metric("종합점수", _score(item.combined_score))
            columns[1].metric("재무종합", _score(item.financial_score))
            columns[2].metric("뉴스·공시", _score(item.nonfinancial_score))
            columns[3].metric(
                "데이터 신뢰도",
                _score(item.decision.data_confidence),
            )
            st.markdown(
                "**선정 근거 주석**  \n"
                f"가치·시장 {item.valuation_score}점 × 55% + "
                f"실적추세 {item.earnings_trend_score}점 × 45% = "
                f"재무종합 {item.financial_score}점, 재무종합 × 70% + "
                f"뉴스·공시 {item.nonfinancial_score}점 × 30%"
            )
            st.caption(
                f"실적 기준: {item.financial_period} · {item.financial_reason}"
            )
            _render_news_disclosure_evidence(item)
    st.caption(
        f"종합 추천 규칙 {INTEGRATED_RULE_VERSION} · 기존 강제필터와 유동성 제외 기준 유지"
    )


def _render_liquid_quality_recommendations(
    result: RecommendationRunResult,
    *,
    settings: Settings,
) -> None:
    st.write(
        "최근 20거래일 중앙 거래대금으로 분석 가능한 상장 보통주의 유동성 순위를 "
        "먼저 계산합니다. "
        f"상위 {LIQUIDITY_POOL_MAX_RANK}위이면서 일평균성 거래대금 하한을 넘긴 종목만 "
        "재무·뉴스·공시 종합평가에 참여하고, 그중 최종점수 상위 5종목을 추천합니다."
    )
    st.caption(
        "하루 거래대금 급증에 흔들리지 않도록 평균 대신 중앙값을 사용합니다. "
        "거래대금 100위 진입이 1차 관문이며, 최종점수는 재무 70% + "
        "뉴스·공시 30%입니다. 상세자료가 부족한 종목은 잠정 추천으로 표시합니다."
    )
    service = IntegratedRecommendationService(settings)
    try:
        liquid_candidates = service.liquid_candidates(
            result.recommendations,
            basis_date=result.basis_date,
            minimum_median_trading_value=(
                settings.phase2_minimum_median_trading_value
            ),
        )
        ranked = service.build_liquid_quality(
            result.recommendations,
            basis_date=result.basis_date,
            minimum_median_trading_value=(
                settings.phase2_minimum_median_trading_value
            ),
        )
    finally:
        service.close()

    refresh_candidates = liquid_candidates
    st.markdown("#### 상세자료 갱신")
    st.caption(
        "빠른 갱신은 100종목의 최신 비교 재무 1개와 최근 공시·뉴스만 "
        "보강합니다. 3년 배당·감사의견 등은 최종 종목 상세화면에서 수집합니다."
    )
    refresh_requested = st.button(
        "거래대금 100종목 빠른 종합자료 갱신",
        key="refresh-liquid-quality-data",
        type="primary",
        width="stretch",
        disabled=not refresh_candidates,
        help=(
            "거래대금 100위 안의 강제 위험필터 통과 종목 전체에 대해 "
            "최신 비교 실적·DART 공시·네이버 뉴스만 증분 갱신합니다. "
            "API 호출 제한에 따라 보통 3~6분이 걸릴 수 있습니다."
        ),
    )
    if not refresh_candidates:
        st.warning("갱신할 거래대금 상위 후보가 아직 계산되지 않았습니다.")
    if refresh_requested:
        progress = st.progress(0.0)
        status = st.empty()
        event_service = EventService(settings)
        analysis_service = StockAnalysisService(settings)

        async def refresh_all_candidates() -> list[str]:
            refresh_errors: list[str] = []
            async with (
                analysis_service.shared_session(),
                event_service.shared_session(),
            ):
                for index, candidate in enumerate(refresh_candidates, start=1):
                    decision = candidate.decision
                    status.caption(
                        f"{index}/{len(refresh_candidates)} · 거래대금 "
                        f"{candidate.trading_value_rank}위 {decision.name} "
                        "빠른 확인 중"
                    )
                    snapshot = analysis_service.snapshot(decision.symbol)
                    financial_years = {
                        row.business_year
                        for row in (
                            snapshot.financial_history
                            if snapshot is not None
                            else ()
                        )
                        if row.value is not None
                    }
                    recent_years = {
                        result.basis_date.year,
                        result.basis_date.year - 1,
                    }
                    if not financial_years.intersection(recent_years):
                        financial_summary = (
                            await analysis_service.refresh_recommendation_financials(
                                symbol=decision.symbol,
                                as_of_date=result.basis_date,
                            )
                        )
                        refresh_errors.extend(financial_summary.errors)
                    event_summary = await event_service.refresh(
                        symbol=decision.symbol,
                        as_of_date=result.basis_date,
                        events_only=True,
                    )
                    refresh_errors.extend(event_summary.errors)
                    progress.progress(index / len(refresh_candidates))
            return refresh_errors

        try:
            refresh_errors = asyncio.run(refresh_all_candidates())
        finally:
            event_service.close()
            analysis_service.close()
        status.caption("거래대금 100종목 빠른 종합자료 갱신 완료")
        if refresh_errors:
            st.warning(
                "일부 공급자 응답을 받지 못했습니다: "
                + " / ".join(dict.fromkeys(refresh_errors[:3]))
            )
        else:
            st.rerun()

    eligible = tuple(item for item in ranked if item.eligible)
    summary = st.columns(4)
    summary[0].metric("거래대금 100위권 검토", f"{len(ranked)}종목")
    summary[1].metric("강제 위험필터 통과", f"{len(eligible)}종목")
    summary[2].metric(
        "거래대금 하한",
        _trading_value(settings.phase2_minimum_median_trading_value),
    )
    summary[3].metric(
        "유동성 풀",
        f"추천 유니버스 상위 {LIQUIDITY_POOL_MAX_RANK}위",
    )
    if not ranked:
        st.info(
            "20거래일 거래대금과 재무·뉴스·공시가 모두 연결된 후보가 없습니다. "
            "2번 카테고리에서 종합자료를 먼저 갱신해 주세요."
        )
        return
    if not eligible:
        st.warning(
            "현재 거래대금 상위 풀에서 재무·비재무 종합 기준까지 통과한 종목이 없습니다."
        )
        with st.expander("제외 사유 확인"):
            st.dataframe(
                [
                    {
                        "종목": item.integrated.decision.name,
                        "거래대금순위": item.trading_value_rank,
                        "20일 중앙 거래대금": _trading_value(
                            item.median_trading_value
                        ),
                        "판정": item.status_label,
                    }
                    for item in ranked[:20]
                ],
                hide_index=True,
                width="stretch",
            )
        return

    st.subheader("추천 상위 5종목")
    st.caption(
        "거래대금 100위 안의 종목만 대상으로 하며, "
        "모든 추천 카테고리는 같은 카드 구성으로 점수·근거·위험을 비교합니다."
    )
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for index, item in enumerate(eligible[:5], start=1):
        integrated = item.integrated
        decision = integrated.decision
        detail_decision = _category_detail_decision(
            decision,
            category_label=f"거래대금 우량주 추천 {index}위",
            score_label="유동성·재무·비재무 종합점수",
            score=item.quality_score,
            status_label=item.status_label,
            integrated=integrated,
        )
        with st.container(border=True):
            st.button(
                f"{medals.get(index, '•')} {index}위 · "
                f"{decision.name} ({decision.symbol})  →",
                key=f"liquid-quality-detail-{decision.symbol}",
                type="primary" if index == 1 else "secondary",
                width="stretch",
                on_click=_open_stock_detail,
                args=(detail_decision,),
            )
            st.caption(
                f"{item.status_label} · 전 종목 거래대금 "
                f"{item.trading_value_rank}/{item.trading_value_universe_count}위"
            )
            columns = st.columns(4)
            columns[0].metric("우량종합", _score(item.quality_score))
            columns[1].metric(
                "20일 중앙 거래대금",
                _trading_value(item.median_trading_value),
            )
            columns[2].metric("재무종합", _score(integrated.financial_score))
            columns[3].metric(
                "뉴스·공시",
                _score(integrated.nonfinancial_score),
            )
            st.markdown(
                "**선정 근거 주석**  \n"
                f"추천 유니버스 거래대금 {item.trading_value_rank}위로 1차 통과 · "
                f"재무 {integrated.financial_score}점 × 70% + "
                f"뉴스·공시 {integrated.nonfinancial_score}점 × 30%"
            )
            st.caption(
                f"거래일 {item.observed_sessions}일 · 실적 기준 "
                f"{integrated.financial_period} · {integrated.financial_reason}"
            )
            if not integrated.has_nonfinancial_data:
                st.warning(
                    "최근 90일 뉴스·공시 원문이 아직 수집되지 않아 비재무점수는 "
                    "중립 50점으로 잠정 반영했습니다. 빠른 종합자료 갱신 후 확정됩니다."
                )
            elif integrated.signal_count == 0:
                st.info(
                    f"최근 90일 뉴스 {integrated.news_article_count}건과 공시 "
                    f"{integrated.disclosure_count}건을 확인했지만 점수에 반영할 "
                    "뚜렷한 긍정·부정 신호가 없어 중립 50점입니다."
                )
            _render_news_disclosure_evidence(integrated)
    st.caption(
        f"우량주 추천 규칙 {LIQUID_QUALITY_RULE_VERSION} · "
        "거래대금 순위는 공식 KRX 일별 거래대금 기준"
    )


def render_recommendations(settings: Settings) -> None:
    st.title("추천종목")
    st.write(
        "KOSPI 전체 종목의 저평가 매력·진입준비도·데이터 신뢰도를 비교해 "
        "현재 검토 우선순위를 보여줍니다."
    )
    st.info(
        "상위 순위는 매수 지시가 아닌 검토 우선순위입니다. 기업 공시와 최근 "
        "위험요인을 함께 확인해야 합니다."
    )

    service = RecommendationService(settings)
    try:
        latest = service.latest()
        profile = service.latest_profile()
        control_left, control_right = st.columns([2, 1])
        with control_left:
            as_of_date = st.date_input(
                "분석 기준일",
                value=now_kst().date(),
                max_value=now_kst().date(),
            )
        with control_right:
            st.write("")
            run_requested = st.button(
                "저장된 추천 결과 새로고침",
                type="primary",
                width="stretch",
            )
        with st.expander("상세 설명 · 분석 설정"):
            st.caption(
                f"편입 목표 {profile.target_stock_count}종목 · "
                f"업종 최대 {profile.max_industry_weight * Decimal(100):.1f}% · "
                f"기업집단 최대 "
                f"{profile.max_company_group_weight * Decimal(100):.1f}%"
            )
            st.write(
                "공식 값이 없는 항목은 추정값으로 채우지 않고 0점 처리하며, "
                "데이터 신뢰도에 별도로 반영합니다."
            )
        if run_requested and settings.app_env == "production":
            requested_at = min(
                datetime.combine(as_of_date, time.max, tzinfo=SEOUL),
                now_kst(),
            )
            started = recommendation_jobs.start(
                settings,
                as_of_at=requested_at,
                profile=profile,
            )
            if not started:
                st.warning("이미 전체 추천 분석이 진행 중입니다.")
            st.rerun()

        job = recommendation_jobs.snapshot()
        if job.status == "running":
            progress = job.processed / job.total if job.total else 0.0
            st.progress(
                progress,
                text=(
                    f"전체 추천 분석 진행 중 · {job.processed}/{job.total} · "
                    f"{job.symbol} · {job.name} · {job.category}"
                ),
            )
            st.caption("분석은 백그라운드에서 계속 진행되며 화면이 자동 갱신됩니다.")
            @st.fragment(run_every="5s")
            def refresh_recommendation_job() -> None:
                if recommendation_jobs.snapshot().status != "running":
                    st.rerun()

            refresh_recommendation_job()
            return
        elif job.status == "failed":
            st.error(f"추천 분석에 실패했습니다: {job.error}")

        if run_requested and settings.app_env != "production":
            progress_bar = st.progress(0.0)
            status = st.empty()

            def update_progress(
                processed: int,
                total: int,
                symbol: str,
                name: str,
                category: str,
            ) -> None:
                progress_bar.progress(
                    processed / total if total else 1.0,
                    text=f"{processed}/{total} · {symbol} · {category}",
                )
                status.caption(
                    "전체 종목의 가치·가격·유동성 점수와 시장국면을 결합하는 중입니다."
                )

            requested_at = min(
                datetime.combine(as_of_date, time.max, tzinfo=SEOUL),
                now_kst(),
            )
            latest = service.run_universe(
                as_of_at=requested_at,
                profile=profile,
                progress=update_progress,
            )
            progress_bar.progress(1.0, text="전체 분석 및 결과 저장 완료")
            status.caption("동일한 입력과 설정이면 저장된 결과를 재사용합니다.")

        if latest is None:
            st.info(
                "저장된 Phase 4 추천 실행이 없습니다. "
                "KOSPI 전체 분석·추천 버튼으로 첫 결과를 생성하세요."
            )
            st.caption(
                "공식 입력이 없는 경우 가짜 추천 대신 데이터 부족 사유만 저장됩니다."
            )
            for item in cached_connection_statuses(settings):
                if item.provider in {"KRX", "OpenDART", "한국투자증권"}:
                    st.caption(
                        f"{item.provider} 연결상태: {item.state.value} · {item.detail}"
                    )
        else:
            st.markdown("### 최신 추천 실행 · 추천 카테고리")
            st.caption(
                f"데이터 기준일 {latest.basis_date} · "
                f"총 {latest.total_count}종목 분석"
            )
            if latest.missing_core_data:
                st.warning(
                    "실행 핵심 입력 부족: "
                    + ", ".join(latest.missing_core_data)
                )
            if not latest.recommendations:
                st.warning(
                    "실제 KOSPI 유니버스가 저장되어 있지 않아 "
                    "분석할 상장 보통주가 없습니다."
                )
                return
            selected_category = _render_category_selector()
            if selected_category == "financial":
                _render_result(
                    latest,
                    entry_threshold=settings.phase4_ready_entry_score,
                )
            elif selected_category == "integrated":
                _render_integrated_recommendations(
                    latest,
                    settings=settings,
                    entry_threshold=settings.phase4_ready_entry_score,
                )
            elif selected_category == "liquid_quality":
                _render_liquid_quality_recommendations(
                    latest,
                    settings=settings,
                )
    except (SQLAlchemyError, OSError, ValueError, ValidationError) as exc:
        st.error(f"추천 실행을 완료하지 못했습니다. 오류 유형: {type(exc).__name__}")
    finally:
        service.close()
