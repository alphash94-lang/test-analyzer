from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from pydantic import HttpUrl
from sqlalchemy import select

from app.db.models.disclosure import Disclosure
from app.db.models.event import EventRecord, NewsArticle
from app.db.models.market import Stock
from app.db.session import create_db_engine, create_session_factory
from app.models.events import (
    EventConfidence,
    EventSentiment,
    KisAnalystOpinionItem,
    KisInvestorFlowItem,
    KisProgramTradingItem,
    KisShortSellingItem,
    NaverNewsItem,
    TextScope,
)
from app.models.metadata import (
    DataMetadata,
    DataState,
    DataTiming,
    FinancialScope,
)
from app.providers.base import ApiResponse
from app.providers.kis_reference import KisReferenceProvider
from app.providers.naver_news import NaverNewsProvider
from app.repositories.disclosure_repository import DisclosureRepository
from app.repositories.event_repository import EventRepository
from app.services.event_rules import (
    classify_disclosure,
    classify_news,
    disclosure_base_title,
)
from app.services.event_service import EventService
from app.ui.events import _format_publication_at
from app.utils.dates import SEOUL
from tests.helpers import make_settings, migrate_database


def _stock(as_of_at: datetime) -> Stock:
    return Stock(
        symbol="000007",
        name_ko="Phase5검증종목",
        dart_corp_code="00123456",
        is_kospi=True,
        security_type="STOCK",
        share_class="COMMON",
        listing_status="LISTED",
        universe_status="INCLUDED",
        quality_state="VALID",
        is_active=True,
        source_provider="KRX",
        source_function="test fixture",
        data_state="AVAILABLE",
        as_of_at=as_of_at,
        collected_at=as_of_at,
        data_timing="NOT_APPLICABLE",
    )


def test_naver_item_uses_only_title_and_provided_summary() -> None:
    item = NaverNewsItem.model_validate(
        {
            "title": "<b>검증기업</b> 자사주 소각 결정",
            "originallink": "https://news.example.test/a?utm_source=naver",
            "link": "https://n.news.naver.com/article/001/1",
            "description": "회사는 &quot;소각&quot; 결정을 공시했다.",
            "pubDate": "Wed, 29 Jul 2026 09:15:00 +0900",
        }
    )

    assert item.title == "검증기업 자사주 소각 결정"
    assert item.summary == '회사는 "소각" 결정을 공시했다.'
    assert item.published_at.tzinfo is not None
    assert item.text_scope == TextScope.TITLE_AND_PROVIDED_SUMMARY
    assert not hasattr(item, "body")


def test_news_after_analysis_date_is_not_normalized() -> None:
    item = NaverNewsItem.model_validate(
        {
            "title": "검증기업 공시",
            "originallink": "https://news.example.test/future",
            "link": "https://n.news.naver.com/article/001/9",
            "description": "검증기업의 제공 요약",
            "pubDate": "Thu, 30 Jul 2026 00:01:00 +0900",
        }
    )

    assert EventService._news_item_is_as_of(
        item,
        as_of_date=date(2026, 7, 29),
    ) is False


def test_phase5_rejects_future_analysis_date(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "future-date.db", monkeypatch)
    service = EventService(make_settings(database_url=database_url))
    try:
        with pytest.raises(ValueError, match="future"):
            asyncio.run(
                service.refresh(
                    symbol="000007",
                    as_of_date=date(9999, 12, 31),
                )
            )
        with pytest.raises(ValueError, match="future"):
            service.snapshot(
                "000007",
                as_of_date=date(9999, 12, 31),
            )
    finally:
        service.close()


def test_naver_provider_without_api_hub_credentials_does_not_call_http() -> None:
    called = False

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    provider = NaverNewsProvider(
        make_settings(),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    response = asyncio.run(provider.fetch_news(query="검증기업", display=10))

    assert response.state == DataState.NOT_CONFIGURED
    assert response.payload is None
    assert called is False


def test_naver_provider_rejects_unverified_response_fields() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "lastBuildDate": "Wed, 29 Jul 2026 09:15:00 +0900",
                "total": 1,
                "start": 1,
                "display": 1,
                "items": [{"title": "필수 필드가 부족한 기사"}],
            },
        )

    provider = NaverNewsProvider(
        make_settings(
            ncp_apigw_api_key_id="test-id",
            ncp_apigw_api_key="test-secret",
        ),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    response = asyncio.run(provider.fetch_news(query="검증기업", display=10))

    assert response.state == DataState.FETCH_FAILED
    assert response.error_code == "SCHEMA_VALIDATION_FAILED"
    assert response.payload is None


def test_kis_opinion_provider_uses_verified_fields_and_never_assumes_currency() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(
                200,
                json={
                    "access_token": "sensitive-token",
                    "token_type": "Bearer",
                    "expires_in": 86400,
                },
            )
        assert request.headers["authorization"] == "Bearer sensitive-token"
        return httpx.Response(
            200,
            json={
                "rt_cd": "0",
                "msg_cd": "MCA00000",
                "msg1": "정상처리 되었습니다.",
                "output": [
                    {
                        "stck_bsop_date": "20260729",
                        "invt_opnn": "매수",
                        "invt_opnn_cls_code": "2",
                        "rgbf_invt_opnn": "중립",
                        "rgbf_invt_opnn_cls_code": "3",
                        "hts_goal_prc": "85000",
                        "stck_prdy_clpr": "70000",
                        "stck_nday_esdg": "0",
                        "nday_dprt": "0",
                        "stft_esdg": "0",
                        "dprt": "0",
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = KisReferenceProvider(
        make_settings(kis_app_key="app-key", kis_app_secret="app-secret"),
        client,
    )
    response = asyncio.run(
        provider.fetch_analyst_opinions(
            symbol="005930",
            begin_date=date(2026, 5, 1),
            end_date=date(2026, 7, 29),
        )
    )
    asyncio.run(client.aclose())

    assert response.state == DataState.AVAILABLE
    assert response.payload is not None
    assert response.payload[0] == KisAnalystOpinionItem.model_validate(
        {
            "stck_bsop_date": "20260729",
            "invt_opnn": "매수",
            "hts_goal_prc": "85000",
        }
    )
    assert response.payload[0].currency is None
    assert len(requests) == 2


def test_kis_provider_rejects_an_uncollected_continuation_page() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(
                200,
                json={"access_token": "token", "expires_in": 86400},
            )
        return httpx.Response(
            200,
            headers={"tr_cont": "M"},
            json={
                "rt_cd": "0",
                "msg_cd": "MCA00000",
                "msg1": "정상처리 되었습니다.",
                "output": [
                    {
                        "stck_bsop_date": "20260729",
                        "invt_opnn": "매수",
                        "hts_goal_prc": "85000",
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = KisReferenceProvider(
        make_settings(kis_app_key="app-key", kis_app_secret="app-secret"),
        client,
    )
    response = asyncio.run(
        provider.fetch_analyst_opinions(
            symbol="005930",
            begin_date=date(2026, 5, 1),
            end_date=date(2026, 7, 29),
        )
    )
    asyncio.run(client.aclose())

    assert response.state == DataState.FETCH_FAILED
    assert response.error_code == "PARTIAL_RESPONSE_UNSUPPORTED"
    assert response.payload is None


def test_kis_program_trading_uses_official_market_aggregate_field() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(
                200,
                json={"access_token": "token", "expires_in": 86400},
            )
        assert request.url.path.endswith("/comp-program-trade-daily")
        assert request.headers["tr_id"] == "FHPPG04600001"
        assert request.url.params["FID_MRKT_CLS_CODE"] == "K"
        return httpx.Response(
            200,
            json={
                "rt_cd": "0",
                "msg_cd": "MCA00000",
                "msg1": "정상처리 되었습니다.",
                "output": [
                    {
                        "stck_bsop_date": "20260729",
                        "whol_entm_ntby_qty": "12,345",
                        "arbt_smtn_ntby_qty": "234",
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = KisReferenceProvider(
        make_settings(kis_app_key="app-key", kis_app_secret="app-secret"),
        client,
    )
    response = asyncio.run(
        provider.fetch_program_trading(
            begin_date=date(2026, 7, 1),
            end_date=date(2026, 7, 29),
        )
    )
    asyncio.run(client.aclose())

    assert response.state == DataState.AVAILABLE
    assert response.payload == [
        KisProgramTradingItem.model_validate(
            {
                "stck_bsop_date": "20260729",
                "whol_entm_ntby_qty": "12345",
            }
        )
    ]


def test_kis_flow_and_short_models_distinguish_zero_from_missing() -> None:
    flow = KisInvestorFlowItem.model_validate(
        {
            "stck_bsop_date": "20260729",
            "frgn_ntby_qty": "0",
            "prsn_ntby_qty": "",
            "orgn_ntby_qty": "-25",
        }
    )
    short = KisShortSellingItem.model_validate(
        {
            "stck_bsop_date": "20260729",
            "ssts_cntg_qty": "0",
            "ssts_tr_pbmn": "",
            "ssts_vol_rlim": "-",
        }
    )

    assert flow.foreign_net_quantity == Decimal(0)
    assert flow.individual_net_quantity is None
    assert flow.institution_net_quantity == Decimal(-25)
    assert short.short_quantity == Decimal(0)
    assert short.short_amount is None
    assert short.short_ratio_percent is None
    with pytest.raises(ValueError):
        KisInvestorFlowItem.model_validate(
            {
                "stck_bsop_date": "20260729",
                "frgn_ntby_qty": "",
                "prsn_ntby_qty": "",
                "orgn_ntby_qty": "",
            }
        )


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            KisInvestorFlowItem,
            {
                "stck_bsop_date": "20260729",
                "frgn_ntby_qty": "1.5",
            },
        ),
        (
            KisProgramTradingItem,
            {
                "stck_bsop_date": "20260729",
                "whol_entm_ntby_qty": "-2.25",
            },
        ),
        (
            KisShortSellingItem,
            {
                "stck_bsop_date": "20260729",
                "ssts_cntg_qty": "0.5",
            },
        ),
        (
            KisShortSellingItem,
            {
                "stck_bsop_date": "20260729",
                "ssts_cntg_qty": "-1",
            },
        ),
        (
            KisShortSellingItem,
            {
                "stck_bsop_date": "20260729",
                "ssts_tr_pbmn": "-1",
            },
        ),
        (
            KisShortSellingItem,
            {
                "stck_bsop_date": "20260729",
                "ssts_vol_rlim": "100.01",
            },
        ),
    ],
)
def test_kis_reference_models_reject_values_that_cannot_be_truthfully_stored(
    model: type[
        KisInvestorFlowItem
        | KisProgramTradingItem
        | KisShortSellingItem
    ],
    payload: dict[str, str],
) -> None:
    with pytest.raises(ValueError):
        model.model_validate(payload)


def test_structured_event_rules_preserve_scope_and_non_definitive_language() -> None:
    disclosure = classify_disclosure("[기재정정] 자기주식소각결정")
    news = classify_news(
        "검증기업, 유상증자 결정",
        "회사가 유상증자 계획을 발표했다.",
    )

    assert disclosure is not None
    assert disclosure.sentiment == EventSentiment.UNCLASSIFIED
    assert disclosure.confidence == EventConfidence.LOW
    assert disclosure.matched_rule.startswith("CORRECTION_REQUIRES_ORIGINAL_REVIEW")
    assert disclosure.text_scope == TextScope.DISCLOSURE_TITLE_ONLY
    assert "확정할 수 없습니다" in disclosure.price_reflection_note
    assert disclosure_base_title("[기재정정] 자기주식소각결정") == (
        "자기주식소각결정"
    )
    assert news.sentiment == EventSentiment.NEGATIVE
    assert news.text_scope == TextScope.TITLE_AND_PROVIDED_SUMMARY
    assert "기사 본문" not in news.used_text


def test_phase5_summary_does_not_hide_current_provider_failure_with_old_data() -> None:
    assert EventService._resolve_refresh_state(
        [DataState.FETCH_FAILED, DataState.AVAILABLE],
        normalized_count=1,
    ) == DataState.FETCH_FAILED
    assert EventService._resolve_refresh_state(
        [DataState.NOT_CONFIGURED] * 6,
        normalized_count=1,
    ) == DataState.NOT_CONFIGURED
    assert EventService._resolve_refresh_state(
        [DataState.AVAILABLE],
        normalized_count=0,
    ) == DataState.MISSING


def test_historical_disclosure_refresh_ignores_later_saved_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "historical-refresh.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    collected_at = datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL)
    with sessions.begin() as session:
        stock = _stock(collected_at)
        session.add(stock)
        session.flush()
        stock_id = stock.id
        session.add_all(
            (
                Disclosure(
                    stock_id=stock.id,
                    corp_code=stock.dart_corp_code,
                    receipt_no="20260101000001",
                    report_name="자기주식소각결정",
                    receipt_date=date(2026, 1, 1),
                    disclosure_type="IMPORTANT_EVENT",
                    source_url=(
                        "https://dart.fss.or.kr/dsaf001/main.do?"
                        "rcpNo=20260101000001"
                    ),
                    is_correction=False,
                    source_provider="OpenDART",
                    source_function="공시검색",
                    data_state="AVAILABLE",
                    as_of_at=collected_at,
                    collected_at=collected_at,
                    data_timing="PERIODIC_DISCLOSURE",
                ),
                Disclosure(
                    stock_id=stock.id,
                    corp_code=stock.dart_corp_code,
                    receipt_no="20260729000001",
                    report_name="유상증자결정",
                    receipt_date=date(2026, 7, 29),
                    disclosure_type="IMPORTANT_EVENT",
                    source_url=(
                        "https://dart.fss.or.kr/dsaf001/main.do?"
                        "rcpNo=20260729000001"
                    ),
                    is_correction=False,
                    source_provider="OpenDART",
                    source_function="공시검색",
                    data_state="AVAILABLE",
                    as_of_at=collected_at,
                    collected_at=collected_at,
                    data_timing="PERIODIC_DISCLOSURE",
                ),
            )
        )

    requested_ranges: list[tuple[date, date]] = []

    class HistoricalDartProvider:
        async def fetch_disclosures(
            self,
            *,
            corp_code: str,
            begin_date: date,
            end_date: date,
            page_no: int,
            publication_type: str | None,
        ) -> ApiResponse[object]:
            del corp_code, page_no, publication_type
            requested_ranges.append((begin_date, end_date))
            return ApiResponse(
                state=DataState.MISSING,
                metadata=DataMetadata(
                    provider="OpenDART",
                    function_name="공시검색",
                    state=DataState.MISSING,
                    collected_at=collected_at,
                    timing=DataTiming.PERIODIC_DISCLOSURE,
                    financial_scope=FinancialScope.NOT_APPLICABLE,
                    is_estimate=False,
                    source_url=HttpUrl(
                        "https://opendart.fss.or.kr/api/list.json"
                    ),
                ),
                error_code="NO_RESULTS",
                error_message="no disclosures",
            )

    service = EventService(
        settings,
        dart_provider=HistoricalDartProvider(),  # type: ignore[arg-type]
    )
    try:
        asyncio.run(
            service._collect_disclosures(
                stock_id=stock_id,
                corp_code="00123456",
                as_of_date=date(2026, 1, 31),
            )
        )
        repository = DisclosureRepository()
        event_repository = EventRepository(title_similarity_threshold=0.92)
        with sessions.begin() as session:
            event_repository.upsert_disclosure_events(
                session,
                stock_id=stock_id,
                disclosures=repository.important_disclosures(
                    session,
                    stock_id,
                ),
            )
        historical_snapshot = service.snapshot(
            "000007",
            as_of_date=date(2026, 1, 31),
        )
        assert historical_snapshot is not None
        assert [item.title for item in historical_snapshot.events] == [
            "자기주식소각결정"
        ]
    finally:
        service.close()

    repository = DisclosureRepository()
    with sessions() as session:
        assert repository.latest_receipt_date(
            session,
            stock_id,
            disclosure_type="IMPORTANT_EVENT",
            as_of_date=date(2026, 1, 31),
        ) == date(2026, 1, 1)
        assert [
            row.receipt_no
            for row in repository.important_disclosures(
                session,
                stock_id,
                as_of_date=date(2026, 1, 31),
            )
        ] == ["20260101000001"]
    assert requested_ranges == [(date(2026, 1, 1), date(2026, 1, 31))]
    engine.dispose()


def test_correction_links_only_to_one_unambiguous_prior_disclosure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "corrections.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    collected_at = datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL)
    repository = DisclosureRepository()
    with sessions.begin() as session:
        stock = _stock(collected_at)
        session.add(stock)
        session.flush()
        original = Disclosure(
            stock_id=stock.id,
            corp_code=stock.dart_corp_code,
            receipt_no="20260728000001",
            original_receipt_no=None,
            report_name="자기주식소각결정",
            receipt_date=date(2026, 7, 28),
            disclosure_type="IMPORTANT_EVENT",
            source_url=(
                "https://dart.fss.or.kr/dsaf001/main.do?"
                "rcpNo=20260728000001"
            ),
            is_correction=False,
            source_provider="OpenDART",
            source_function="공시검색",
            data_state="AVAILABLE",
            as_of_at=collected_at,
            collected_at=collected_at,
            data_timing="PERIODIC_DISCLOSURE",
        )
        correction = Disclosure(
            stock_id=stock.id,
            corp_code=stock.dart_corp_code,
            receipt_no="20260729000001",
            original_receipt_no=None,
            report_name="[기재정정] 자기주식소각결정",
            receipt_date=date(2026, 7, 29),
            disclosure_type="IMPORTANT_EVENT",
            source_url=(
                "https://dart.fss.or.kr/dsaf001/main.do?"
                "rcpNo=20260729000001"
            ),
            is_correction=True,
            source_provider="OpenDART",
            source_function="공시검색",
            data_state="AVAILABLE",
            as_of_at=collected_at,
            collected_at=collected_at,
            data_timing="PERIODIC_DISCLOSURE",
        )
        session.add_all((original, correction))
        session.flush()

        linked, ambiguous = repository.link_corrections(
            session,
            stock_id=stock.id,
        )

        assert linked == 1
        assert ambiguous == 0
        assert correction.original_receipt_no == original.receipt_no
        assert correction.correction_link_state == "LINKED"

        competing_original = Disclosure(
            stock_id=stock.id,
            corp_code=stock.dart_corp_code,
            receipt_no="20260727000001",
            original_receipt_no=None,
            report_name="자기주식소각결정",
            receipt_date=date(2026, 7, 27),
            disclosure_type="IMPORTANT_EVENT",
            source_url=(
                "https://dart.fss.or.kr/dsaf001/main.do?"
                "rcpNo=20260727000001"
            ),
            is_correction=False,
            source_provider="OpenDART",
            source_function="공시검색",
            data_state="AVAILABLE",
            as_of_at=collected_at,
            collected_at=collected_at,
            data_timing="PERIODIC_DISCLOSURE",
        )
        session.add(competing_original)
        session.flush()

        linked, ambiguous = repository.link_corrections(
            session,
            stock_id=stock.id,
        )

        assert linked == 0
        assert ambiguous == 1
        assert correction.original_receipt_no is None
        assert correction.correction_link_state == "AMBIGUOUS"
    engine.dispose()


def test_news_repository_deduplicates_canonical_url_and_similar_title(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "news.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    repository = EventRepository(title_similarity_threshold=0.92)
    collected_at = datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL)
    first = NaverNewsItem.model_validate(
        {
            "title": "검증기업, 자기주식 소각 결정",
            "originallink": "https://news.example.test/a?utm_source=naver",
            "link": "https://n.news.naver.com/article/001/1",
            "description": "검증기업이 자기주식 소각을 결정했다.",
            "pubDate": "Wed, 29 Jul 2026 09:15:00 +0900",
        }
    )
    repeated = first.model_copy(
        update={
            "original_url": "https://news.example.test/a?utm_medium=search",
            "provider_url": "https://n.news.naver.com/article/001/2",
        }
    )
    with sessions.begin() as session:
        stock = _stock(collected_at)
        session.add(stock)
        session.flush()
        stored, duplicate = repository.upsert_news(
            session,
            stock=stock,
            query="검증기업",
            items=(first, repeated),
            raw_response_id=None,
            collected_at=collected_at,
        )

        assert stored == 1
        assert duplicate == 1
        article = session.scalars(select(NewsArticle)).one()
        assert article.publisher is None
        assert article.original_url == "https://news.example.test/a?utm_source=naver"
        assert len(session.scalars(select(EventRecord)).all()) == 1
    engine.dispose()


def test_phase5_event_payload_is_reproducible() -> None:
    classified = classify_news(
        "검증기업 자기주식 소각",
        "검증기업은 자기주식 소각을 결정했다고 밝혔다.",
    )
    first = json.dumps(classified.model_dump(mode="json"), sort_keys=True)
    second = json.dumps(
        classify_news(
            "검증기업 자기주식 소각",
            "검증기업은 자기주식 소각을 결정했다고 밝혔다.",
        ).model_dump(mode="json"),
        sort_keys=True,
    )

    assert first == second


def test_disclosure_publication_display_does_not_invent_midnight_precision() -> None:
    published_at = datetime(2026, 7, 29, 0, 0, tzinfo=SEOUL)

    assert _format_publication_at(
        source_kind="DISCLOSURE",
        published_at=published_at,
    ) == "2026-07-29 (접수일, 시각 미제공)"
    assert _format_publication_at(
        source_kind="NEWS",
        published_at=datetime(2026, 7, 29, 9, 15, tzinfo=SEOUL),
    ) == "2026-07-29 09:15 KST"


def test_phase5_ui_uses_the_current_streamlit_dataframe_width_argument() -> None:
    source = Path("app/ui/events.py").read_text(encoding="utf-8")

    assert "use_container_width" not in source
