from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

import streamlit as st
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models.disclosure import Disclosure
from app.db.models.event import (
    AnalystOpinion,
    EventWatchlistItem,
    InvestorFlow,
    NewsArticle,
    ProgramTrading,
    ShortSelling,
)
from app.db.models.market import PriceDaily, Stock
from app.db.models.market_analysis import IndexDaily
from app.db.models.quality import ApiRawResponse
from app.db.session import create_db_engine, create_session_factory
from app.models.ecos import EcosObservation
from app.models.status import ConnectionState
from app.repositories.event_watchlist_repository import WATCHLIST_CATEGORY
from app.services.connection_status import get_connection_statuses
from app.utils.dates import restore_database_kst


def _number(value: Decimal | None, *, integer: bool = False) -> int | float | None:
    if value is None:
        return None
    return int(value) if integer else float(value)


def _datetime_text(value: datetime | None) -> str:
    if value is None:
        return "-"
    return restore_database_kst(value).strftime("%Y-%m-%d %H:%M:%S KST")


def _render_stock_master(session: Session) -> None:
    search = st.text_input(
        "종목 검색",
        placeholder="종목코드 또는 종목명을 입력하세요",
        key="krx_preview_stock_search",
    ).strip()
    limit = st.select_slider(
        "표시 개수",
        options=[25, 50, 100, 250, 500],
        value=100,
        key="krx_preview_stock_limit",
    )
    statement = select(Stock).where(Stock.source_provider == "KRX")
    if search:
        statement = statement.where(
            or_(
                Stock.symbol.contains(search, autoescape=True),
                Stock.name_ko.contains(search, autoescape=True),
            )
        )
    stocks = session.scalars(statement.order_by(Stock.symbol).limit(limit)).all()
    if not stocks:
        st.info("조건에 맞는 KRX 종목 기본정보가 없습니다.")
        return

    rows = [
        {
            "종목코드": stock.symbol,
            "종목명": stock.name_ko,
            "시장": stock.market_name or "-",
            "증권구분": stock.security_group_name or "-",
            "주식종류": stock.certificate_type_name or "-",
            "상장일": stock.listed_on.isoformat() if stock.listed_on else "-",
            "상장주식수": stock.listed_shares_raw or "-",
            "검증상태": stock.quality_state,
            "수집시각": _datetime_text(stock.collected_at),
        }
        for stock in stocks
    ]
    st.caption(f"검색 결과 {len(rows):,}개 · 최대 {limit:,}개 표시")
    st.dataframe(rows, width="stretch", hide_index=True, height=560)


def _render_daily_prices(session: Session) -> None:
    trade_dates = session.scalars(
        select(PriceDaily.trade_date)
        .where(PriceDaily.source_provider == "KRX")
        .distinct()
        .order_by(PriceDaily.trade_date.desc())
        .limit(60)
    ).all()
    if not trade_dates:
        st.info(
            "저장된 KRX 일별 가격이 없습니다. "
            "`scripts.update_daily_prices` 수집 후 이 탭에서 확인할 수 있습니다."
        )
        return

    selected_date = st.selectbox(
        "거래일",
        trade_dates,
        format_func=lambda value: value.isoformat(),
        key="krx_preview_price_date",
    )
    limit = st.select_slider(
        "표시 개수",
        options=[25, 50, 100, 250, 500],
        value=100,
        key="krx_preview_price_limit",
    )
    rows = session.execute(
        select(Stock, PriceDaily)
        .join(PriceDaily, PriceDaily.stock_id == Stock.id)
        .where(
            PriceDaily.source_provider == "KRX",
            PriceDaily.trade_date == selected_date,
        )
        .order_by(Stock.symbol)
        .limit(limit)
    ).all()
    preview = [
        {
            "거래일": price.trade_date.isoformat(),
            "종목코드": stock.symbol,
            "종목명": stock.name_ko,
            "시가": _number(price.open_price),
            "고가": _number(price.high_price),
            "저가": _number(price.low_price),
            "종가": _number(price.close_price),
            "거래량": _number(price.volume, integer=True),
            "거래대금": _number(price.trading_value, integer=True),
            "시가총액": _number(price.market_cap, integer=True),
            "수집시각": _datetime_text(price.collected_at),
        }
        for stock, price in rows
    ]
    st.caption(f"{selected_date.isoformat()} · {len(preview):,}개 종목 표시")
    st.dataframe(preview, width="stretch", hide_index=True, height=560)


def _render_indexes(session: Session) -> None:
    indexes = session.scalars(
        select(IndexDaily)
        .where(IndexDaily.source_provider == "KRX")
        .order_by(IndexDaily.trade_date.desc(), IndexDaily.index_name)
        .limit(500)
    ).all()
    if not indexes:
        st.info(
            "저장된 KOSPI 지수 데이터가 없습니다. "
            "`scripts.update_daily_index` 수집 후 이 탭에서 확인할 수 있습니다."
        )
        return

    rows = [
        {
            "거래일": item.trade_date.isoformat(),
            "지수분류": item.index_class,
            "지수명": item.index_name,
            "시가": _number(item.open),
            "고가": _number(item.high),
            "저가": _number(item.low),
            "종가": _number(item.close),
            "전일대비": _number(item.previous_day_change),
            "등락률(%)": _number(item.fluctuation_rate),
            "거래량": _number(item.volume, integer=True),
            "수집시각": _datetime_text(item.collected_at),
        }
        for item in indexes
    ]
    st.caption(f"최근 데이터 {len(rows):,}개 표시")
    st.dataframe(rows, width="stretch", hide_index=True, height=560)


def _render_collection_history(session: Session) -> None:
    attempts = session.scalars(
        select(ApiRawResponse)
        .where(ApiRawResponse.provider == "KRX")
        .order_by(ApiRawResponse.received_at.desc())
        .limit(100)
    ).all()
    if not attempts:
        st.info("저장된 KRX 수집 이력이 없습니다.")
        return

    rows = [
        {
            "수집시각": _datetime_text(attempt.received_at),
            "기준시각": _datetime_text(attempt.as_of_at),
            "API": attempt.function_name,
            "HTTP": attempt.http_status,
            "데이터상태": attempt.data_state,
            "오류코드": attempt.error_code or "-",
        }
        for attempt in attempts
    ]
    st.caption("인증키와 원시 응답 본문은 표시하지 않습니다.")
    st.dataframe(rows, width="stretch", hide_index=True, height=480)


def _preview_stock(session: Session) -> Stock | None:
    watchlist_ids = select(EventWatchlistItem.stock_id).where(
        EventWatchlistItem.category == WATCHLIST_CATEGORY
    )
    stocks = session.scalars(
        select(Stock)
        .where(
            Stock.is_active.is_(True),
            Stock.is_kospi.is_(True),
            Stock.security_type == "STOCK",
            Stock.share_class == "COMMON",
        )
        .order_by(
            Stock.id.in_(watchlist_ids).desc(),
            Stock.name_ko,
            Stock.symbol,
        )
    ).all()
    if not stocks:
        st.info("미리보기할 활성 KOSPI 보통주가 없습니다.")
        return None
    labels = {
        f"{stock.symbol} · {stock.name_ko}": stock
        for stock in stocks
    }
    selected = st.selectbox(
        "미리보기 종목",
        options=list(labels),
        key="integrated_preview_stock",
        help="관심종목이 목록 상단에 우선 표시됩니다.",
    )
    return labels[selected]


def _render_dart_disclosures(session: Session, stock: Stock | None) -> None:
    st.subheader("OpenDART 공시 미리보기")
    if stock is None:
        return
    disclosures = session.scalars(
        select(Disclosure)
        .where(Disclosure.stock_id == stock.id)
        .order_by(Disclosure.receipt_date.desc(), Disclosure.receipt_no.desc())
        .limit(100)
    ).all()
    if not disclosures:
        st.info(
            f"{stock.name_ko}에 저장된 OpenDART 공시가 없습니다. "
            "관심종목 수집을 실행하세요."
        )
        return
    st.dataframe(
        [
            {
                "접수일": item.receipt_date.isoformat(),
                "보고서명": item.report_name,
                "제출인": item.filer_name or "-",
                "공시유형": item.disclosure_type or "-",
                "정정": "정정공시" if item.is_correction else "원공시",
                "원문": item.source_url or "-",
                "수집시각": _datetime_text(item.collected_at),
                "상태": item.data_state,
            }
            for item in disclosures
        ],
        width="stretch",
        hide_index=True,
        height=560,
    )


def _render_kis_preview(session: Session, stock: Stock | None) -> None:
    st.subheader("KIS 투자의견·수급·공매도")
    if stock is None:
        return
    opinions = session.scalars(
        select(AnalystOpinion)
        .where(
            AnalystOpinion.stock_id == stock.id,
            AnalystOpinion.source_provider == "한국투자증권",
        )
        .order_by(AnalystOpinion.published_date.desc())
        .limit(100)
    ).all()
    flows = session.scalars(
        select(InvestorFlow)
        .where(
            InvestorFlow.stock_id == stock.id,
            InvestorFlow.source_provider == "한국투자증권",
        )
        .order_by(InvestorFlow.trade_date.desc(), InvestorFlow.investor_type)
        .limit(300)
    ).all()
    shorts = session.scalars(
        select(ShortSelling)
        .where(
            ShortSelling.stock_id == stock.id,
            ShortSelling.source_provider == "한국투자증권",
        )
        .order_by(ShortSelling.trade_date.desc())
        .limit(100)
    ).all()
    programs = session.scalars(
        select(ProgramTrading)
        .where(ProgramTrading.source_provider == "한국투자증권")
        .order_by(ProgramTrading.trade_date.desc())
        .limit(100)
    ).all()
    opinion_tab, flow_tab, short_tab, program_tab = st.tabs(
        ["투자의견", "투자자 수급", "공매도", "프로그램매매"]
    )
    with opinion_tab:
        if opinions:
            st.dataframe(
                [
                    {
                        "발표일": item.published_date.isoformat(),
                        "증권사": item.broker,
                        "투자의견": item.opinion or "-",
                        "목표주가": _number(item.target_price),
                        "통화": item.currency or "-",
                        "수집시각": _datetime_text(item.collected_at),
                    }
                    for item in opinions
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("저장된 KIS 투자의견이 없습니다.")
    with flow_tab:
        if flows:
            st.dataframe(
                [
                    {
                        "거래일": item.trade_date.isoformat(),
                        "투자자": item.investor_type,
                        "순매수수량": _number(
                            item.net_purchase_quantity,
                            integer=True,
                        ),
                        "순매수금액": _number(item.net_purchase_amount),
                        "수집시각": _datetime_text(item.collected_at),
                    }
                    for item in flows
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("저장된 KIS 투자자 수급이 없습니다.")
    with short_tab:
        if shorts:
            st.dataframe(
                [
                    {
                        "거래일": item.trade_date.isoformat(),
                        "공매도수량": _number(
                            item.short_quantity,
                            integer=True,
                        ),
                        "공매도대금": _number(item.short_amount),
                        "공매도비중(%)": _number(item.short_ratio),
                        "수집시각": _datetime_text(item.collected_at),
                    }
                    for item in shorts
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("저장된 KIS 공매도 데이터가 없습니다.")
    with program_tab:
        if programs:
            st.dataframe(
                [
                    {
                        "시장": item.market_code,
                        "거래일": item.trade_date.isoformat(),
                        "순매수수량": _number(
                            item.net_purchase_quantity,
                            integer=True,
                        ),
                        "순매수금액": _number(item.net_purchase_amount),
                        "수집시각": _datetime_text(item.collected_at),
                    }
                    for item in programs
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("저장된 KIS 프로그램매매 데이터가 없습니다.")


def _render_naver_news(session: Session, stock: Stock | None) -> None:
    st.subheader("네이버 종목 뉴스")
    if stock is None:
        return
    articles = session.scalars(
        select(NewsArticle)
        .where(
            NewsArticle.stock_id == stock.id,
            NewsArticle.source_provider == "Naver API HUB",
        )
        .order_by(NewsArticle.published_at.desc())
        .limit(100)
    ).all()
    if not articles:
        st.info(
            f"{stock.name_ko}에 저장된 네이버 뉴스가 없습니다. "
            "관심종목 수집을 실행하세요."
        )
        return
    st.dataframe(
        [
            {
                "기사일시": _datetime_text(item.published_at),
                "제목": item.title,
                "요약": item.summary,
                "원문": item.original_url or item.provider_url,
                "수집시각": _datetime_text(item.collected_at),
                "상태": item.data_state,
            }
            for item in articles
        ],
        width="stretch",
        hide_index=True,
        height=560,
    )
    st.caption(
        "네이버 API가 제공한 제목과 요약만 표시하며 기사 본문은 저장하지 않습니다."
    )


def _ecos_observations(session: Session) -> dict[str, list[EcosObservation]]:
    responses = session.scalars(
        select(ApiRawResponse)
        .where(
            ApiRawResponse.provider == "ECOS",
            ApiRawResponse.data_state == "AVAILABLE",
            ApiRawResponse.response_body.is_not(None),
        )
        .order_by(ApiRawResponse.received_at.desc(), ApiRawResponse.id.desc())
    ).all()
    latest_by_function: dict[str, ApiRawResponse] = {}
    for response in responses:
        latest_by_function.setdefault(response.function_name, response)
    adapter = TypeAdapter(list[EcosObservation])
    parsed: dict[str, list[EcosObservation]] = {}
    for function_name, response in latest_by_function.items():
        try:
            payload = json.loads(response.response_body or "{}")
            rows = payload["StatisticSearch"]["row"]
            observations = adapter.validate_python(rows)
        except (KeyError, TypeError, json.JSONDecodeError, ValidationError):
            continue
        parsed[function_name] = sorted(
            observations,
            key=lambda item: item.observed_on,
        )
    return parsed


def _render_ecos_charts(session: Session) -> None:
    st.subheader("ECOS 금리·환율 차트")
    series = _ecos_observations(session)
    if not series:
        st.info(
            "차트로 표시할 ECOS 공식 원응답이 없습니다. "
            "`python -m scripts.update_ecos_macro`를 실행하세요."
        )
        return
    for function_name, observations in series.items():
        latest = observations[-1]
        st.markdown(f"#### {function_name.removeprefix('통계조회: ')}")
        st.metric(
            "최신값",
            f"{latest.value:,} {latest.unit_name}",
            help=f"기준일 {latest.observed_on.isoformat()}",
        )
        st.line_chart(
            [
                {
                    "날짜": item.observed_on,
                    "값": float(item.value),
                }
                for item in observations
            ],
            x="날짜",
            y="값",
        )


def _render_all_latest(session: Session) -> None:
    st.subheader("전체 데이터 최신 수집 시각")
    responses = session.scalars(
        select(ApiRawResponse)
        .order_by(ApiRawResponse.received_at.desc(), ApiRawResponse.id.desc())
        .limit(2000)
    ).all()
    if not responses:
        st.info("저장된 API 수집 이력이 없습니다.")
        return
    latest_by_function: dict[tuple[str, str], ApiRawResponse] = {}
    latest_success_by_provider: dict[str, ApiRawResponse] = {}
    for response in responses:
        latest_by_function.setdefault(
            (response.provider, response.function_name),
            response,
        )
        if response.data_state == "AVAILABLE":
            latest_success_by_provider.setdefault(response.provider, response)
    provider_columns = st.columns(
        max(1, min(5, len(latest_success_by_provider)))
    )
    for index, (provider, response) in enumerate(
        latest_success_by_provider.items()
    ):
        provider_columns[index % len(provider_columns)].metric(
            provider,
            _datetime_text(response.received_at),
        )
    st.dataframe(
        [
            {
                "공급자": response.provider,
                "API": response.function_name,
                "최근 시도": _datetime_text(response.received_at),
                "기준시각": _datetime_text(response.as_of_at),
                "상태": response.data_state,
                "HTTP": response.http_status,
                "오류코드": response.error_code or "-",
            }
            for response in latest_by_function.values()
        ],
        width="stretch",
        hide_index=True,
        height=560,
    )
    st.caption("인증키와 원시 응답 본문은 표시하지 않습니다.")


def render_krx_preview(settings: Settings) -> None:
    st.markdown(
        '<div class="status-kicker">INTEGRATED API DATA PREVIEW</div>',
        unsafe_allow_html=True,
    )
    st.title("통합 API 데이터 미리보기")
    st.write(
        "KRX·OpenDART·KIS·네이버·ECOS에서 수집해 검증·저장한 정보를 조회합니다. "
        "이 화면은 로컬 데이터베이스를 읽기 전용으로 사용합니다."
    )

    krx_status = next(
        item for item in get_connection_statuses(settings) if item.provider == "KRX"
    )
    if krx_status.state == ConnectionState.CONNECTED:
        st.success(f"KRX 연결됨 · {krx_status.detail}")
    elif krx_status.state == ConnectionState.STALE:
        st.warning(f"KRX 데이터 최신성 확인 필요 · {krx_status.detail}")
    else:
        st.warning(f"KRX 상태: {krx_status.state.value} · {krx_status.detail}")

    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    try:
        with sessions() as session:
            stock_count = session.scalar(
                select(func.count()).select_from(Stock).where(
                    Stock.source_provider == "KRX"
                )
            )
            price_count = session.scalar(
                select(func.count()).select_from(PriceDaily).where(
                    PriceDaily.source_provider == "KRX"
                )
            )
            index_count = session.scalar(
                select(func.count()).select_from(IndexDaily).where(
                    IndexDaily.source_provider == "KRX"
                )
            )
            last_received = session.scalar(
                select(func.max(ApiRawResponse.received_at)).where(
                    ApiRawResponse.provider == "KRX",
                    ApiRawResponse.data_state == "AVAILABLE",
                )
            )

            metric_columns = st.columns(4)
            metric_columns[0].metric("종목 기본정보", f"{stock_count or 0:,}개")
            metric_columns[1].metric("일별 가격", f"{price_count or 0:,}건")
            metric_columns[2].metric("지수 데이터", f"{index_count or 0:,}건")
            metric_columns[3].metric("마지막 성공 수집", _datetime_text(last_received))

            st.divider()
            preview_stock = _preview_stock(session)
            (
                stock_tab,
                price_tab,
                index_tab,
                dart_tab,
                kis_tab,
                news_tab,
                ecos_tab,
                latest_tab,
                history_tab,
            ) = st.tabs(
                [
                    "종목 기본정보",
                    "일별 가격",
                    "KOSPI 지수",
                    "OpenDART 공시 미리보기",
                    "KIS 투자의견·수급·공매도",
                    "네이버 종목 뉴스",
                    "ECOS 금리·환율 차트",
                    "전체 데이터 최신 수집 시각",
                    "KRX 수집 이력",
                ]
            )
            with stock_tab:
                _render_stock_master(session)
            with price_tab:
                _render_daily_prices(session)
            with index_tab:
                _render_indexes(session)
            with dart_tab:
                _render_dart_disclosures(session, preview_stock)
            with kis_tab:
                _render_kis_preview(session, preview_stock)
            with news_tab:
                _render_naver_news(session, preview_stock)
            with ecos_tab:
                _render_ecos_charts(session)
            with latest_tab:
                _render_all_latest(session)
            with history_tab:
                _render_collection_history(session)
    finally:
        engine.dispose()
