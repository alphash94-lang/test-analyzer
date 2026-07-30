from __future__ import annotations

import asyncio
import re
from datetime import datetime

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.models.events import Phase5Snapshot
from app.services.event_service import EventService
from app.services.event_watchlist_service import EventWatchlistService
from app.utils.dates import now_kst

_SYMBOL = re.compile(r"^\d{6}$")
_STATE_LABELS = {
    "AVAILABLE": "사용 가능",
    "NOT_CONFIGURED": "키 미설정",
    "NOT_VERIFIED": "연결 미검증",
    "FETCH_FAILED": "수집 실패",
    "STALE": "갱신 필요",
    "MISSING": "데이터 없음",
    "CONFLICT": "충돌",
    "UNSUPPORTED": "지원 보류",
}
_SENTIMENT_LABELS = {
    "POSITIVE": "긍정",
    "NEUTRAL": "중립",
    "NEGATIVE": "부정",
    "UNCLASSIFIED": "분류 불가",
}


def _format_publication_at(*, source_kind: str, published_at: datetime) -> str:
    if source_kind == "DISCLOSURE":
        return f"{published_at.date().isoformat()} (접수일, 시각 미제공)"
    return published_at.strftime("%Y-%m-%d %H:%M KST")


def _render_availability(snapshot: Phase5Snapshot) -> None:
    st.subheader("연결·제공 가능 상태")
    for item in snapshot.availability:
        st.caption(
            f"{item.provider} · {_STATE_LABELS[item.state.value]} · {item.reason}"
        )
    st.dataframe(
        [
            {
                "데이터": item.label,
                "provider": item.provider,
                "상태": _STATE_LABELS[item.state.value],
                "공식 기능": item.official_function or "확인 불가",
                "구체적 사유": item.reason,
            }
            for item in snapshot.availability
        ],
        width="stretch",
        hide_index=True,
    )


def _render_events(
    snapshot: Phase5Snapshot,
    *,
    title: str = "공시·뉴스 이벤트",
    empty_message: str | None = None,
) -> None:
    st.subheader(title)
    if not snapshot.events:
        st.info(
            empty_message
            or (
                "저장된 공식 이벤트가 없습니다. API 키와 종목 매핑을 "
                "확인한 뒤 수집 명령 또는 아래 버튼을 실행하세요."
            )
        )
        return
    st.dataframe(
        [
            {
                "제목": item.title,
                "발생일": (
                    item.event_date.isoformat()
                    if item.event_date is not None
                    else "확인 불가"
                ),
                "공시일·기사일": _format_publication_at(
                    source_kind=item.source_kind,
                    published_at=item.published_at,
                ),
                "출처": f"{item.source_provider} · {item.source_kind}",
                "원문 링크": item.source_url or "확인 불가",
                "긍정·중립·부정": _SENTIMENT_LABELS[item.sentiment.value],
                "신뢰도": item.confidence.value,
                "판단근거": item.rationale,
                "사용 텍스트 범위": item.used_text_scope.value,
                "주가 반영 가능성": item.price_reflection_note,
                "정정 여부": "정정" if item.is_correction else "원자료",
                "원공시 접수번호": item.original_source_key or "확인 불가",
                "정정 연결상태": item.correction_link_state.value,
                "수집시각": item.collected_at.strftime(
                    "%Y-%m-%d %H:%M:%S KST"
                ),
                "데이터 상태": item.data_state.value,
            }
            for item in snapshot.events
        ],
        width="stretch",
        hide_index=True,
    )
    st.caption(
        "뉴스 분석은 네이버 API가 제공한 제목과 요약만 사용합니다. "
        "기사 본문을 수집하거나 읽은 것으로 표현하지 않습니다."
    )


def _render_analyst(snapshot: Phase5Snapshot, settings: Settings) -> None:
    st.subheader("애널리스트 의견·추정치")
    st.caption(
        "증권사 투자의견·목표주가·EPS 추정치는 추정 데이터이며, "
        "외국인·기관의 실제 매매와 별개입니다."
    )
    if not snapshot.analyst_opinions and not snapshot.earnings_estimates:
        st.info(
            "검증된 공식 응답 필드로 저장된 애널리스트 의견·EPS 추정치가 "
            "없습니다. 임의 목표주가나 EPS를 표시하지 않습니다."
        )
        return
    if len(snapshot.analyst_opinions) < settings.phase5_analyst_minimum_sample:
        st.warning(
            f"최근 {settings.phase5_analyst_window_days}일 동일 증권사 최신 의견 "
            f"기준 표본이 {settings.phase5_analyst_minimum_sample}개 미만이므로 "
            "애널리스트 종합판단은 계산하지 않습니다."
        )
    if snapshot.analyst_opinions:
        st.dataframe(
            [
                {
                    "증권사": item.broker,
                    "투자의견": item.opinion or "확인 불가",
                    "목표주가": item.target_price,
                    "통화": item.currency or "확인 불가",
                    "발표일": item.published_date.isoformat(),
                    "출처": item.provider,
                    "확정·추정": "추정",
                    "공식 API endpoint": item.source_url or "확인 불가",
                }
                for item in snapshot.analyst_opinions
            ],
            width="stretch",
            hide_index=True,
        )
    if snapshot.earnings_estimates:
        st.dataframe(
            [
                {
                    "증권사": item.broker,
                    "지표": item.metric_code,
                    "대상기간": item.fiscal_period,
                    "추정값": item.estimate_value,
                    "단위": item.unit or "확인 불가",
                    "통화": item.currency or "확인 불가",
                    "발표일": item.published_date.isoformat(),
                    "출처": item.provider,
                    "확정·추정": "추정",
                }
                for item in snapshot.earnings_estimates
            ],
            width="stretch",
            hide_index=True,
        )


def _render_flows(snapshot: Phase5Snapshot) -> None:
    st.subheader("실제 수급")
    st.caption(
        "실제 외국인·기관·개인 매매, 프로그램매매, 공매도는 "
        "애널리스트 투자의견과 합치거나 같은 의미로 표시하지 않습니다."
    )
    if not snapshot.investor_flows:
        st.info(
            "검증된 공식 응답 필드로 저장된 실제 수급 데이터가 없습니다. "
            "0건을 순매수 0으로 바꾸지 않습니다."
        )
    else:
        st.dataframe(
            [
                {
                    "거래일": item.trade_date.isoformat(),
                    "투자자": item.investor_type,
                    "순매수 수량": item.net_purchase_quantity,
                    "순매수 금액": item.net_purchase_amount,
                    "통화": item.currency or "확인 불가",
                    "단위": item.unit or "원응답 단위 확인 필요",
                    "출처": item.provider,
                }
                for item in snapshot.investor_flows
            ],
            width="stretch",
            hide_index=True,
        )
    st.subheader("프로그램매매")
    if not snapshot.program_trading:
        st.info(
            "검증된 공식 응답 필드로 저장된 프로그램매매 데이터가 없습니다. "
            "누락을 0으로 표시하지 않습니다."
        )
    else:
        st.dataframe(
            [
                {
                    "시장": item.market_code,
                    "거래일": item.trade_date.isoformat(),
                    "전체 위탁 순매수 수량": item.net_purchase_quantity,
                    "원응답 필드": item.provider_field,
                    "단위": item.unit or "공식 응답 단위 미표기",
                    "출처": item.provider,
                }
                for item in snapshot.program_trading
            ],
            width="stretch",
            hide_index=True,
        )
    st.subheader("공매도")
    if not snapshot.short_selling:
        st.info(
            "검증된 공식 응답 필드로 저장된 공매도 데이터가 없습니다. "
            "누락을 0으로 표시하지 않습니다."
        )
    else:
        st.dataframe(
            [
                {
                    "거래일": item.trade_date.isoformat(),
                    "공매도 체결 수량": item.short_quantity,
                    "공매도 거래대금": item.short_amount,
                    "공매도 거래량 비중(%)": item.short_ratio_percent,
                    "통화": item.currency or "확인 불가",
                    "출처": item.provider,
                }
                for item in snapshot.short_selling
            ],
            width="stretch",
            hide_index=True,
        )


def _render_watchlist_event_preview(
    settings: Settings,
    *,
    symbol: str,
    name_ko: str,
) -> None:
    st.divider()
    st.subheader(f"{name_ko} ({symbol}) 관련 공시·뉴스")
    service = EventService(settings)
    try:
        collect_clicked = st.button(
            "선택 종목 데이터 지금 수집",
            key=f"watchlist_collect_{symbol}",
            help="OpenDART 공시, 네이버 뉴스와 KIS 참고 데이터를 갱신합니다.",
        )
        if collect_clicked:
            with st.spinner(f"{name_ko} 공식 데이터를 수집하고 있습니다."):
                summary = asyncio.run(
                    service.refresh(
                        symbol=symbol,
                        as_of_date=now_kst().date(),
                    )
                )
            if summary.state.value == "AVAILABLE":
                st.success(
                    "수집 완료 · "
                    f"중요공시 {summary.disclosures_stored}건 · "
                    f"뉴스 {summary.news_stored}건 · "
                    f"중복 제외 {summary.news_deduplicated}건"
                )
            else:
                st.warning(
                    f"수집 상태: {_STATE_LABELS[summary.state.value]}"
                )
            for error in summary.errors:
                st.error(error)

        snapshot = service.snapshot(symbol, as_of_date=now_kst().date())
        if snapshot is None:
            st.warning("저장된 종목을 찾을 수 없습니다.")
            return
        disclosures = service.disclosures(
            symbol,
            as_of_date=now_kst().date(),
        ) or ()
        news = tuple(
            item for item in snapshot.events if item.source_kind == "NEWS"
        )
        disclosure_tab, news_tab = st.tabs(
            [f"OpenDART 공시 {len(disclosures)}", f"네이버 뉴스 {len(news)}"]
        )
        with disclosure_tab:
            st.subheader("OpenDART 전체 공시")
            if disclosures:
                st.dataframe(
                    [
                        {
                            "접수일": item.receipt_date.isoformat(),
                            "보고서명": item.report_name,
                            "제출인": item.filer_name or "-",
                            "중요공시 분류": (
                                "중요"
                                if item.disclosure_type == "IMPORTANT_EVENT"
                                else "일반"
                            ),
                            "정정": (
                                "정정공시" if item.is_correction else "원공시"
                            ),
                            "원문 링크": item.source_url or "-",
                            "수집시각": item.collected_at.strftime(
                                "%Y-%m-%d %H:%M:%S KST"
                            ),
                        }
                        for item in disclosures
                    ],
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info(
                    "저장된 공시가 없습니다. 위 수집 버튼을 실행하세요."
                )
        with news_tab:
            _render_events(
                snapshot.model_copy(update={"events": news}),
                title="네이버 종목 뉴스",
                empty_message=(
                    "저장된 종목 뉴스가 없습니다. 위 수집 버튼을 실행하세요."
                ),
            )
    finally:
        service.close()


def _render_watchlist(settings: Settings) -> None:
    service = EventWatchlistService(settings)
    try:
        eligible = service.eligible_stocks()
        current = service.list_items()
        current_symbols = {item.symbol for item in current}
        available = [
            (symbol, name)
            for symbol, name in eligible
            if symbol not in current_symbols
        ]
        labels = {
            f"{symbol} · {name}": symbol for symbol, name in available
        }

        st.subheader(f"관심종목 · {len(current)}/50")
        st.caption(
            "활성 KOSPI 보통주 중 20~50개 운영을 권장합니다. "
            "등록 목록은 KIS·네이버 뉴스·공시 수집 범위로 사용됩니다."
        )
        selected_labels = st.multiselect(
            "추가할 종목",
            options=list(labels),
            placeholder="종목명 또는 6자리 코드로 검색",
            key="event_watchlist_add",
        )
        if st.button(
            "관심종목 추가",
            disabled=not selected_labels,
            key="event_watchlist_add_button",
        ):
            added = service.add_symbols(
                [labels[label] for label in selected_labels]
            )
            st.success(f"관심종목 {added}개를 추가했습니다.")
            current = service.list_items()

        if current:
            table_state = st.dataframe(
                [
                    {
                        "종목코드": item.symbol,
                        "종목명": item.name_ko,
                        "등록일": item.created_at.strftime("%Y-%m-%d"),
                    }
                    for item in current
                ],
                width="stretch",
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key="event_watchlist_table",
            )
            st.caption("관심종목 행을 클릭하면 아래에서 공시와 뉴스를 확인합니다.")
            current_labels = {
                f"{item.symbol} · {item.name_ko}": item.symbol
                for item in current
            }
            remove_labels = st.multiselect(
                "삭제할 종목",
                options=list(current_labels),
                placeholder="목록에서 삭제할 종목 선택",
                key="event_watchlist_remove",
            )
            if st.button(
                "선택 종목 삭제",
                disabled=not remove_labels,
                key="event_watchlist_remove_button",
            ):
                removed = service.remove_symbols(
                    [current_labels[label] for label in remove_labels]
                )
                st.success(f"관심종목 {removed}개를 삭제했습니다.")

            selection_state = table_state.get("selection", {})
            selected_rows = selection_state.get("rows", [])
            if selected_rows:
                selected_index = selected_rows[0]
                if 0 <= selected_index < len(current):
                    selected_item = current[selected_index]
                    _render_watchlist_event_preview(
                        settings,
                        symbol=selected_item.symbol,
                        name_ko=selected_item.name_ko,
                    )
        else:
            st.info(
                "등록된 관심종목이 없습니다. KOSPI 보통주를 검색해 "
                "추가하세요."
            )
        st.code(
            r".\.venv\Scripts\python.exe -m scripts.update_all",
            language="powershell",
        )
        st.caption(
            "위 한 줄을 실행하면 관심종목만 공시·뉴스·KIS 단계에서 "
            "순서대로 갱신합니다."
        )
    finally:
        service.close()


def _render_symbol_lookup(settings: Settings) -> None:
    service: EventService | None = None
    try:
        service = EventService(settings)
        empty_snapshot = Phase5Snapshot(availability=service.availability())
        symbol = st.text_input(
            "6자리 종목코드",
            placeholder="저장된 KOSPI 종목코드 입력",
        ).strip()
        as_of_date = st.date_input("수집 기준일", value=now_kst().date())
        collect_clicked = st.button(
            "공식 공시·뉴스 수집",
            disabled=not bool(_SYMBOL.fullmatch(symbol)),
        )
        if collect_clicked:
            summary = asyncio.run(
                service.refresh(symbol=symbol, as_of_date=as_of_date)
            )
            if summary.state.value == "AVAILABLE":
                st.success(
                    "수집 완료 · "
                    f"중요공시 {summary.disclosures_stored}건 · "
                    f"뉴스 {summary.news_stored}건 · "
                    f"중복 제외 {summary.news_deduplicated}건"
                )
            else:
                st.warning(
                    f"수집 상태: {_STATE_LABELS[summary.state.value]}"
                )
            for error in summary.errors:
                st.error(error)
        if not symbol:
            _render_availability(empty_snapshot)
            st.info(
                "저장된 공식 이벤트가 없습니다. 종목코드를 입력하면 저장된 공식 "
                "이벤트만 조회합니다. "
                "예시 이벤트나 가짜 수급은 표시하지 않습니다."
            )
            return
        if not _SYMBOL.fullmatch(symbol):
            st.error("종목코드는 6자리 숫자여야 합니다.")
            _render_availability(empty_snapshot)
            return
        snapshot = service.snapshot(symbol, as_of_date=as_of_date)
        if snapshot is None:
            st.error(
                "저장된 종목을 찾을 수 없습니다. 먼저 KRX 종목 마스터를 "
                "수집하세요."
            )
            _render_availability(empty_snapshot)
            return
        event_tab, analyst_tab, flow_tab, status_tab = st.tabs(
            ["공시·뉴스", "애널리스트", "실제 수급", "제공 상태"]
        )
        with event_tab:
            _render_events(snapshot)
        with analyst_tab:
            _render_analyst(snapshot, settings)
        with flow_tab:
            _render_flows(snapshot)
        with status_tab:
            _render_availability(snapshot)
    finally:
        if service is not None:
            service.close()


def render_events(settings: Settings) -> None:
    st.markdown(
        '<div class="status-kicker">Phase 5 · Events and reference data</div>',
        unsafe_allow_html=True,
    )
    st.title("공시·뉴스·애널리스트·수급")
    st.caption(
        "공식 공시를 우선하며 뉴스, 애널리스트 추정, 실제 매매를 "
        "서로 다른 데이터로 표시합니다."
    )
    try:
        watchlist_tab, lookup_tab = st.tabs(["관심종목", "종목별 조회"])
        with watchlist_tab:
            _render_watchlist(settings)
        with lookup_tab:
            _render_symbol_lookup(settings)
    except (OSError, SQLAlchemyError, ValueError) as exc:
        st.error(f"Phase 5 화면 초기화 실패: {type(exc).__name__}")
        st.caption("DB migration과 DATABASE_URL 설정을 확인하세요.")
