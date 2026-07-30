from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any, cast

from pydantic import SecretStr
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models.disclosure import Disclosure
from app.db.models.event import EventWatchlistItem
from app.db.models.market import Stock
from app.db.models.quality import ApiRawResponse
from app.db.session import create_db_engine, create_session_factory
from app.models.events import (
    KisAnalystOpinionItem,
    KisInvestorFlowItem,
    KisProgramTradingItem,
    KisShortSellingItem,
    NaverNewsItem,
    Phase5RefreshSummary,
    Phase5Snapshot,
    ReferenceAvailability,
)
from app.models.financial import DartDisclosurePage
from app.models.metadata import DataState
from app.providers.base import ApiResponse
from app.providers.dart_analysis import (
    DART_DISCLOSURE_ENDPOINT,
    DART_DISCLOSURE_FUNCTION,
    OpenDartAnalysisProvider,
)
from app.providers.kis_reference import (
    KIS_FLOW_ENDPOINT,
    KIS_FLOW_FUNCTION,
    KIS_OPINION_ENDPOINT,
    KIS_OPINION_FUNCTION,
    KIS_PROGRAM_ENDPOINT,
    KIS_PROGRAM_FUNCTION,
    KIS_SHORT_ENDPOINT,
    KIS_SHORT_FUNCTION,
    KisReferenceProvider,
)
from app.providers.naver_news import (
    NAVER_NEWS_ENDPOINT,
    NAVER_NEWS_FUNCTION,
    NaverNewsProvider,
)
from app.repositories.data_quality_repository import DataQualityRepository
from app.repositories.disclosure_repository import DisclosureRepository
from app.repositories.event_repository import EventRepository
from app.repositories.raw_response_repository import RawResponseRepository
from app.services.event_rules import classify_disclosure
from app.utils.dates import now_kst


class EventService:
    def __init__(
        self,
        settings: Settings,
        *,
        dart_provider: OpenDartAnalysisProvider | None = None,
        news_provider: NaverNewsProvider | None = None,
        kis_provider: KisReferenceProvider | None = None,
    ) -> None:
        self._settings = settings
        self._dart = dart_provider or OpenDartAnalysisProvider(settings)
        self._news = news_provider or NaverNewsProvider(settings)
        self._kis = kis_provider or KisReferenceProvider(settings)
        self._raw = RawResponseRepository(settings)
        self._quality = DataQualityRepository()
        self._disclosures = DisclosureRepository()
        self._events = EventRepository(
            title_similarity_threshold=settings.phase5_news_title_similarity,
            rule_version=settings.phase5_event_rule_version,
        )
        self._engine = create_db_engine(settings)
        self._sessions = create_session_factory(self._engine)

    async def refresh(
        self,
        *,
        symbol: str,
        as_of_date: date,
    ) -> Phase5RefreshSummary:
        if as_of_date > now_kst().date():
            raise ValueError("as_of_date must not be in the future")
        started_at = now_kst()
        with self._sessions() as session:
            stock = session.scalar(
                self._stock_query(symbol)
            )
            if stock is None:
                return self._summary(
                    state=DataState.MISSING,
                    symbol=symbol,
                    started_at=started_at,
                    errors=("종목을 찾을 수 없습니다.",),
                )
            stock_id = stock.id
            corp_code = stock.dart_corp_code
            custom_news_query = session.scalar(
                select(EventWatchlistItem.news_query).where(
                    EventWatchlistItem.stock_id == stock.id,
                    EventWatchlistItem.category == "INTEREST",
                )
            )
            news_query = (
                custom_news_query
                or stock.abbreviated_name
                or stock.name_ko
            )
            news_names = tuple(
                dict.fromkeys(
                    name
                    for name in (
                        custom_news_query,
                        stock.abbreviated_name,
                        stock.name_ko,
                    )
                    if name
                )
            )

        errors: list[str] = []
        provider_states: list[DataState] = []
        disclosures_stored = 0
        disclosure_events_stored = 0
        corrections_linked = 0
        corrections_ambiguous = 0
        if corp_code:
            (
                dart_state,
                disclosures_stored,
                dart_errors,
            ) = await self._collect_disclosures(
                stock_id=stock_id,
                corp_code=corp_code,
                as_of_date=as_of_date,
            )
            provider_states.append(dart_state)
            errors.extend(dart_errors)
            with self._sessions.begin() as session:
                corrections_linked, corrections_ambiguous = (
                    self._disclosures.link_corrections(
                        session,
                        stock_id=stock_id,
                        as_of_date=as_of_date,
                    )
                )
                disclosures = self._disclosures.important_disclosures(
                    session,
                    stock_id,
                    as_of_date=as_of_date,
                )
                disclosure_events_stored = self._events.upsert_disclosure_events(
                    session,
                    stock_id=stock_id,
                    disclosures=disclosures,
                )
        else:
            provider_states.append(DataState.MISSING)
            errors.append("OpenDART 고유번호가 매핑되지 않았습니다.")

        news_response = await self._news.fetch_news(
            query=news_query,
            display=self._settings.phase5_news_display,
            sort="date",
        )
        provider_states.append(news_response.state)
        news_raw_id = self._save_raw(
            provider="Naver API HUB",
            response=news_response,
            function_name=NAVER_NEWS_FUNCTION,
            endpoint=NAVER_NEWS_ENDPOINT,
            request_parameters={
                "query": news_query,
                "display": str(self._settings.phase5_news_display),
                "start": "1",
                "sort": "date",
                "format": "json",
            },
        )
        news_stored = 0
        news_deduplicated = 0
        if (
            news_response.state == DataState.AVAILABLE
            and news_response.payload is not None
        ):
            name_matched_items = tuple(
                item
                for item in news_response.payload.items
                if any(
                    name in f"{item.title} {item.summary}"
                    for name in news_names
                )
            )
            relevant_items = tuple(
                item
                for item in name_matched_items
                if self._news_item_is_as_of(
                    item,
                    as_of_date=as_of_date,
                )
            )
            with self._sessions.begin() as session:
                stock = session.get(Stock, stock_id)
                if stock is None:
                    self._set_normalization_failure(
                        session,
                        raw_response_id=news_raw_id,
                        error_code="MISSING_STOCK",
                        error_message="종목 레코드가 없습니다.",
                    )
                    errors.append("뉴스 저장 중 종목 레코드가 사라졌습니다.")
                else:
                    news_stored, news_deduplicated = self._events.upsert_news(
                        session,
                        stock=stock,
                        query=news_query,
                        items=relevant_items,
                        raw_response_id=news_raw_id,
                        collected_at=news_response.metadata.collected_at,
                    )
                    self._set_normalization_success(
                        session,
                        raw_response_id=news_raw_id,
                    )
                    if len(relevant_items) < len(news_response.payload.items):
                        self._quality.add(
                            session,
                            entity_type="news_query",
                            entity_id=symbol,
                            provider="Naver API HUB",
                            issue_code="QUERY_RELEVANCE_FILTERED",
                            severity="INFO",
                            data_state=DataState.AVAILABLE,
                            message=(
                                "종목명이 제목·제공 요약에 없거나 기준일 "
                                "이후인 검색 결과를 정규화 저장에서 제외했습니다."
                            ),
                            context={
                                "received": len(news_response.payload.items),
                                "retained": len(relevant_items),
                                "query_mismatch": (
                                    len(news_response.payload.items)
                                    - len(name_matched_items)
                                ),
                                "after_as_of_date": (
                                    len(name_matched_items)
                                    - len(relevant_items)
                                ),
                            },
                        )
        elif news_response.state not in {
            DataState.MISSING,
            DataState.NOT_CONFIGURED,
        }:
            errors.append(
                news_response.error_message
                or "네이버 뉴스 검색을 사용할 수 없습니다."
            )

        (
            analyst_opinions_stored,
            investor_flows_stored,
            program_trading_stored,
            short_selling_stored,
            kis_states,
            kis_errors,
        ) = await self._collect_kis_reference(
            stock_id=stock_id,
            symbol=symbol,
            as_of_date=as_of_date,
        )
        provider_states.extend(kis_states)
        errors.extend(kis_errors)
        with self._sessions() as session:
            existing_event_count = len(
                self._events.views(
                    session,
                    stock_id,
                    as_of_date=as_of_date,
                )
            )
        normalized_count = (
            existing_event_count
            + analyst_opinions_stored
            + investor_flows_stored
            + program_trading_stored
            + short_selling_stored
        )
        state = self._resolve_refresh_state(
            provider_states,
            normalized_count=normalized_count,
        )
        return self._summary(
            state=state,
            symbol=symbol,
            started_at=started_at,
            disclosures_stored=disclosures_stored,
            disclosure_events_stored=disclosure_events_stored,
            corrections_linked=corrections_linked,
            corrections_ambiguous=corrections_ambiguous,
            news_stored=news_stored,
            news_deduplicated=news_deduplicated,
            analyst_opinions_stored=analyst_opinions_stored,
            investor_flows_stored=investor_flows_stored,
            program_trading_stored=program_trading_stored,
            short_selling_stored=short_selling_stored,
            errors=tuple(errors),
        )

    def snapshot(
        self,
        symbol: str,
        *,
        as_of_date: date | None = None,
    ) -> Phase5Snapshot | None:
        today = now_kst().date()
        basis_date = as_of_date or today
        if basis_date > today:
            raise ValueError("as_of_date must not be in the future")
        with self._sessions() as session:
            stock = session.scalar(self._stock_query(symbol))
            if stock is None:
                return None
            return Phase5Snapshot(
                symbol=stock.symbol,
                events=self._events.views(
                    session,
                    stock.id,
                    as_of_date=basis_date,
                ),
                analyst_opinions=self._events.analyst_views(
                    session,
                    stock.id,
                    since_date=(
                        basis_date
                        - timedelta(
                            days=self._settings.phase5_analyst_window_days
                        )
                    ),
                    as_of_date=basis_date,
                ),
                earnings_estimates=self._events.estimate_views(
                    session,
                    stock.id,
                    as_of_date=basis_date,
                ),
                investor_flows=self._events.flow_views(
                    session,
                    stock.id,
                    as_of_date=basis_date,
                ),
                program_trading=self._events.program_views(
                    session,
                    since_date=(
                        basis_date
                        - timedelta(
                            days=self._settings.phase5_analyst_window_days
                        )
                    ),
                    as_of_date=basis_date,
                ),
                short_selling=self._events.short_views(
                    session,
                    stock.id,
                    as_of_date=basis_date,
                ),
                availability=self.availability(),
            )

    def disclosures(
        self,
        symbol: str,
        *,
        as_of_date: date | None = None,
    ) -> tuple[Disclosure, ...] | None:
        today = now_kst().date()
        basis_date = as_of_date or today
        if basis_date > today:
            raise ValueError("as_of_date must not be in the future")
        with self._sessions() as session:
            stock = session.scalar(self._stock_query(symbol))
            if stock is None:
                return None
            return self._disclosures.disclosures(
                session,
                stock.id,
                as_of_date=basis_date,
            )

    def availability(self) -> tuple[ReferenceAvailability, ...]:
        dart_ready = self._has_secret(self._settings.dart_api_key)
        news_ready = self._has_secret(
            self._settings.ncp_apigw_api_key_id
        ) and self._has_secret(self._settings.ncp_apigw_api_key)
        kis_ready = self._has_secret(
            self._settings.kis_app_key
        ) and self._has_secret(self._settings.kis_app_secret)
        dart_state = self._provider_state(
            "OpenDART",
            DART_DISCLOSURE_FUNCTION,
            configured=dart_ready,
        )
        news_state = self._provider_state(
            "Naver API HUB",
            NAVER_NEWS_FUNCTION,
            configured=news_ready,
        )
        opinion_state = self._provider_state(
            "한국투자증권",
            KIS_OPINION_FUNCTION,
            configured=kis_ready,
        )
        flow_state = self._provider_state(
            "한국투자증권",
            KIS_FLOW_FUNCTION,
            configured=kis_ready,
        )
        program_state = self._provider_state(
            "한국투자증권",
            KIS_PROGRAM_FUNCTION,
            configured=kis_ready,
        )
        short_state = self._provider_state(
            "한국투자증권",
            KIS_SHORT_FUNCTION,
            configured=kis_ready,
        )
        kis_unimplemented_state = (
            DataState.NOT_VERIFIED if kis_ready else DataState.NOT_CONFIGURED
        )
        kis_ready_reason = (
            "키가 설정됐으며 실제 수집 성공 여부는 원응답 상태로 판단합니다."
            if kis_ready
            else "필요 환경변수: KIS_APP_KEY, KIS_APP_SECRET"
        )
        kis_unverified_reason = (
            "공식 기능 경로는 확인했지만 현재 앱의 응답 필드 계약과 "
            "정규화 어댑터를 검증하지 않았습니다."
            if kis_ready
            else "필요 환경변수: KIS_APP_KEY, KIS_APP_SECRET"
        )
        return (
            ReferenceAvailability(
                label="DART 중요공시",
                provider="OpenDART",
                state=dart_state,
                reason=(
                    "키가 설정됐으며 실제 수집 성공 여부는 원응답 상태로 판단합니다."
                    if dart_ready
                    else "필요 환경변수: DART_API_KEY"
                ),
                official_function="공시검색",
            ),
            ReferenceAvailability(
                label="KIND 공식 상태·이벤트",
                provider="KIND",
                state=DataState.UNSUPPORTED,
                reason=(
                    "공식 공개 API 계약과 자동 수집 권한이 확인되지 않아 "
                    "임의 엔드포인트를 사용하지 않습니다."
                ),
            ),
            ReferenceAvailability(
                label="네이버 뉴스",
                provider="Naver API HUB",
                state=news_state,
                reason=(
                    "API HUB 키가 설정됐으며 실제 수집 성공 여부는 "
                    "원응답 상태로 판단합니다."
                    if news_ready
                    else (
                        "필요 환경변수: NCP_APIGW_API_KEY_ID, "
                        "NCP_APIGW_API_KEY"
                    )
                ),
                official_function="뉴스 검색 API",
            ),
            ReferenceAvailability(
                label="애널리스트 의견·목표주가",
                provider="한국투자증권",
                state=opinion_state,
                reason=kis_ready_reason,
                official_function="국내주식 종목투자의견",
            ),
            ReferenceAvailability(
                label="EPS 추정치",
                provider="한국투자증권",
                state=kis_unimplemented_state,
                reason=(
                    f"{kis_unverified_reason} EPS 응답 필드의 공식 의미가 불충분해 "
                    "추정값을 만들지 않습니다."
                ),
                official_function="국내주식 종목추정실적",
            ),
            ReferenceAvailability(
                label="외국인·기관·개인 수급",
                provider="한국투자증권",
                state=flow_state,
                reason=kis_ready_reason,
                official_function="종목별 투자자매매동향(일별)",
            ),
            ReferenceAvailability(
                label="프로그램매매",
                provider="한국투자증권",
                state=program_state,
                reason=kis_ready_reason,
                official_function="프로그램매매 종합현황(일별)",
            ),
            ReferenceAvailability(
                label="공매도",
                provider="한국투자증권",
                state=short_state,
                reason=kis_ready_reason,
                official_function="국내주식 공매도 일별추이",
            ),
            ReferenceAvailability(
                label="대차·신용",
                provider="한국투자증권",
                state=kis_unimplemented_state,
                reason=kis_unverified_reason,
                official_function=(
                    "대차거래 추이 / 국내주식 신용잔고 일별추이"
                ),
            ),
        )

    def close(self) -> None:
        self._engine.dispose()

    async def _collect_disclosures(
        self,
        *,
        stock_id: int,
        corp_code: str,
        as_of_date: date,
    ) -> tuple[DataState, int, list[str]]:
        lower_bound = as_of_date - timedelta(
            days=self._settings.phase5_disclosure_lookback_days
        )
        with self._sessions() as session:
            latest_date = self._disclosures.latest_receipt_date(
                session,
                stock_id,
                disclosure_type="IMPORTANT_EVENT",
                as_of_date=as_of_date,
            )
        begin_date = (
            max(lower_bound, latest_date) if latest_date is not None else lower_bound
        )
        state = DataState.MISSING
        errors: list[str] = []
        stored = 0
        page_no = 1
        total_pages = 1
        while page_no <= total_pages:
            response = await self._dart.fetch_disclosures(
                corp_code=corp_code,
                begin_date=begin_date,
                end_date=as_of_date,
                page_no=page_no,
                publication_type=None,
            )
            state = response.state
            raw_id = self._save_raw(
                provider="OpenDART",
                response=response,
                function_name=DART_DISCLOSURE_FUNCTION,
                endpoint=DART_DISCLOSURE_ENDPOINT,
                request_parameters={
                    "corp_code": corp_code,
                    "bgn_de": begin_date.strftime("%Y%m%d"),
                    "end_de": as_of_date.strftime("%Y%m%d"),
                    "last_reprt_at": "N",
                    "sort": "date",
                    "sort_mth": "desc",
                    "page_no": str(page_no),
                    "page_count": "100",
                },
            )
            if response.state != DataState.AVAILABLE or response.payload is None:
                if response.state not in {
                    DataState.MISSING,
                    DataState.NOT_CONFIGURED,
                }:
                    errors.append(
                        response.error_message
                        or "OpenDART 중요공시 검색을 사용할 수 없습니다."
                    )
                break
            page: DartDisclosurePage = response.payload
            total_pages = page.total_page
            if not 1 <= total_pages <= 10_000:
                errors.append("OpenDART 공시검색 페이지 수가 비정상입니다.")
                state = DataState.FETCH_FAILED
                break
            important_items = tuple(
                item
                for item in page.items
                if classify_disclosure(
                    item.report_name,
                    rule_version=self._settings.phase5_event_rule_version,
                )
                is not None
            )
            general_items = tuple(
                item for item in page.items if item not in important_items
            )
            with self._sessions.begin() as session:
                stock = session.get(Stock, stock_id)
                if stock is None:
                    self._set_normalization_failure(
                        session,
                        raw_response_id=raw_id,
                        error_code="MISSING_STOCK",
                        error_message="종목 레코드가 없습니다.",
                    )
                    errors.append("공시 저장 중 종목 레코드가 사라졌습니다.")
                    state = DataState.FETCH_FAILED
                    break
                stored += self._disclosures.upsert(
                    session,
                    stock=stock,
                    items=important_items,
                    raw_response_id=raw_id,
                    disclosure_type="IMPORTANT_EVENT",
                    collected_at=response.metadata.collected_at,
                )
                self._disclosures.upsert(
                    session,
                    stock=stock,
                    items=general_items,
                    raw_response_id=raw_id,
                    disclosure_type="GENERAL",
                    collected_at=response.metadata.collected_at,
                )
                self._set_normalization_success(
                    session,
                    raw_response_id=raw_id,
                )
            page_no += 1
        return state, stored, errors

    async def _collect_kis_reference(
        self,
        *,
        stock_id: int,
        symbol: str,
        as_of_date: date,
    ) -> tuple[int, int, int, int, list[DataState], list[str]]:
        begin_date = as_of_date - timedelta(
            days=self._settings.phase5_analyst_window_days
        )
        calls = (
            (
                "opinions",
                await self._kis.fetch_analyst_opinions(
                    symbol=symbol,
                    begin_date=begin_date,
                    end_date=as_of_date,
                ),
                KIS_OPINION_FUNCTION,
                KIS_OPINION_ENDPOINT,
                {
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_COND_SCR_DIV_CODE": "16633",
                    "FID_INPUT_ISCD": symbol,
                    "FID_INPUT_DATE_1": begin_date.strftime("%Y%m%d"),
                    "FID_INPUT_DATE_2": as_of_date.strftime("%Y%m%d"),
                },
            ),
            (
                "flows",
                await self._kis.fetch_investor_flows(
                    symbol=symbol,
                    as_of_date=as_of_date,
                ),
                KIS_FLOW_FUNCTION,
                KIS_FLOW_ENDPOINT,
                {
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": symbol,
                    "FID_INPUT_DATE_1": as_of_date.strftime("%Y%m%d"),
                    "FID_ORG_ADJ_PRC": "",
                    "FID_ETC_CLS_CODE": "",
                },
            ),
            (
                "program",
                await self._kis.fetch_program_trading(
                    begin_date=begin_date,
                    end_date=as_of_date,
                ),
                KIS_PROGRAM_FUNCTION,
                KIS_PROGRAM_ENDPOINT,
                {
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_MRKT_CLS_CODE": "K",
                    "FID_INPUT_DATE_1": begin_date.strftime("%Y%m%d"),
                    "FID_INPUT_DATE_2": as_of_date.strftime("%Y%m%d"),
                },
            ),
            (
                "short",
                await self._kis.fetch_short_selling(
                    symbol=symbol,
                    begin_date=begin_date,
                    end_date=as_of_date,
                ),
                KIS_SHORT_FUNCTION,
                KIS_SHORT_ENDPOINT,
                {
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": symbol,
                    "FID_INPUT_DATE_1": begin_date.strftime("%Y%m%d"),
                    "FID_INPUT_DATE_2": as_of_date.strftime("%Y%m%d"),
                },
            ),
        )
        counts = {"opinions": 0, "flows": 0, "program": 0, "short": 0}
        states: list[DataState] = []
        errors: list[str] = []
        for kind, response, function_name, endpoint, parameters in calls:
            states.append(response.state)
            raw_id = self._save_raw(
                provider="한국투자증권",
                response=response,
                function_name=function_name,
                endpoint=endpoint,
                request_parameters=parameters,
            )
            if response.state == DataState.AVAILABLE and response.payload:
                with self._sessions.begin() as session:
                    if kind == "program":
                        counts[kind] = self._events.upsert_program_trading(
                            session,
                            items=cast(
                                list[KisProgramTradingItem],
                                response.payload,
                            ),
                            raw_response_id=raw_id,
                            collected_at=response.metadata.collected_at,
                        )
                        self._set_normalization_success(
                            session,
                            raw_response_id=raw_id,
                        )
                        continue
                    stock = session.get(Stock, stock_id)
                    if stock is None:
                        self._set_normalization_failure(
                            session,
                            raw_response_id=raw_id,
                            error_code="MISSING_STOCK",
                            error_message="종목 레코드가 없습니다.",
                        )
                        errors.append(
                            f"{function_name} 저장 중 종목 레코드가 사라졌습니다."
                        )
                        continue
                    if kind == "opinions":
                        counts[kind] = self._events.upsert_analyst_opinions(
                            session,
                            stock=stock,
                            items=cast(
                                list[KisAnalystOpinionItem],
                                response.payload,
                            ),
                            raw_response_id=raw_id,
                            collected_at=response.metadata.collected_at,
                            source_url=endpoint,
                        )
                    elif kind == "flows":
                        counts[kind] = self._events.upsert_investor_flows(
                            session,
                            stock=stock,
                            items=cast(
                                list[KisInvestorFlowItem],
                                response.payload,
                            ),
                            raw_response_id=raw_id,
                            collected_at=response.metadata.collected_at,
                        )
                    else:
                        counts[kind] = self._events.upsert_short_selling(
                            session,
                            stock=stock,
                            items=cast(
                                list[KisShortSellingItem],
                                response.payload,
                            ),
                            raw_response_id=raw_id,
                            collected_at=response.metadata.collected_at,
                        )
                    self._set_normalization_success(
                        session,
                        raw_response_id=raw_id,
                    )
            elif response.state not in {
                DataState.MISSING,
                DataState.NOT_CONFIGURED,
            }:
                errors.append(
                    response.error_message
                    or f"{function_name} 수집을 사용할 수 없습니다."
                )
        return (
            counts["opinions"],
            counts["flows"],
            counts["program"],
            counts["short"],
            states,
            errors,
        )

    def _save_raw(
        self,
        *,
        provider: str,
        response: ApiResponse[Any],
        function_name: str,
        endpoint: str,
        request_parameters: Mapping[str, object],
    ) -> int | None:
        with self._sessions.begin() as session:
            row = self._raw.save(
                session,
                provider=provider,
                function_name=function_name,
                endpoint=endpoint,
                request_parameters=dict(request_parameters),
                response=response,
            )
            session.flush()
            return row.id if row is not None else None

    @staticmethod
    def _news_item_is_as_of(
        item: NaverNewsItem,
        *,
        as_of_date: date,
    ) -> bool:
        return item.published_at.date() <= as_of_date

    @staticmethod
    def _resolve_refresh_state(
        provider_states: list[DataState],
        *,
        normalized_count: int,
    ) -> DataState:
        if any(item == DataState.FETCH_FAILED for item in provider_states):
            return DataState.FETCH_FAILED
        if provider_states and all(
            item == DataState.NOT_CONFIGURED for item in provider_states
        ):
            return DataState.NOT_CONFIGURED
        if (
            normalized_count > 0
            and any(item == DataState.AVAILABLE for item in provider_states)
        ):
            return DataState.AVAILABLE
        return DataState.MISSING

    @staticmethod
    def _stock_query(symbol: str) -> Select[tuple[Stock]]:
        return select(Stock).where(Stock.symbol == symbol)

    @staticmethod
    def _has_secret(secret: SecretStr | None) -> bool:
        return bool(secret and secret.get_secret_value().strip())

    def _provider_state(
        self,
        provider: str,
        function_name: str,
        *,
        configured: bool,
    ) -> DataState:
        if not configured:
            return DataState.NOT_CONFIGURED
        with self._sessions() as session:
            row = session.scalar(
                select(ApiRawResponse)
                .where(
                    ApiRawResponse.provider == provider,
                    ApiRawResponse.function_name == function_name,
                )
                .order_by(
                    ApiRawResponse.received_at.desc(),
                    ApiRawResponse.id.desc(),
                )
                .limit(1)
            )
        if row is None:
            return DataState.NOT_VERIFIED
        return DataState(row.data_state)

    @staticmethod
    def _set_normalization_success(
        session: Session,
        *,
        raw_response_id: int | None,
    ) -> None:
        RawResponseRepository.set_normalization_result(
            session,
            raw_response_id,
            success=True,
        )

    @staticmethod
    def _set_normalization_failure(
        session: Session,
        *,
        raw_response_id: int | None,
        error_code: str,
        error_message: str,
    ) -> None:
        RawResponseRepository.set_normalization_result(
            session,
            raw_response_id,
            success=False,
            error_code=error_code,
            error_message=error_message,
        )

    @staticmethod
    def _summary(
        *,
        state: DataState,
        symbol: str,
        started_at: datetime,
        disclosures_stored: int = 0,
        disclosure_events_stored: int = 0,
        corrections_linked: int = 0,
        corrections_ambiguous: int = 0,
        news_stored: int = 0,
        news_deduplicated: int = 0,
        analyst_opinions_stored: int = 0,
        investor_flows_stored: int = 0,
        program_trading_stored: int = 0,
        short_selling_stored: int = 0,
        errors: tuple[str, ...] = (),
    ) -> Phase5RefreshSummary:
        return Phase5RefreshSummary(
            state=state,
            symbol=symbol,
            started_at=started_at,
            finished_at=now_kst(),
            disclosures_stored=disclosures_stored,
            disclosure_events_stored=disclosure_events_stored,
            corrections_linked=corrections_linked,
            corrections_ambiguous=corrections_ambiguous,
            news_stored=news_stored,
            news_deduplicated=news_deduplicated,
            analyst_opinions_stored=analyst_opinions_stored,
            investor_flows_stored=investor_flows_stored,
            program_trading_stored=program_trading_stored,
            short_selling_stored=short_selling_stored,
            errors=errors,
        )
