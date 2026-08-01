from __future__ import annotations

import asyncio
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.db.models.disclosure import Disclosure
from app.db.models.financial import (
    AuditOpinion,
    Dividend,
    DividendFact,
    FinancialAccount,
    FinancialStatement,
)
from app.db.models.market import Stock
from app.db.models.quality import ApiRawResponse
from app.db.session import create_db_engine, create_session_factory
from app.models.financial import (
    DartAuditOpinionItem,
    DartCompanyProfileItem,
    DartDisclosureItem,
    DartDividendFactItem,
    DartFinancialAccountItem,
)
from app.models.metadata import (
    DataMetadata,
    DataState,
    DataTiming,
    FinancialScope,
)
from app.providers.base import ApiResponse
from app.providers.dart_analysis import OpenDartAnalysisProvider
from app.repositories.financial_repository import FinancialRepository
from app.services.account_mapping import map_xbrl_account
from app.services.dividend_service import parse_confirmed_dividend_fact
from app.services.stock_analysis_service import (
    StockAnalysisService,
    _incremental_report_codes,
)
from app.utils.dates import now_kst
from app.utils.financial_math import (
    cumulative_to_quarters,
    ttm_from_annual_and_interim,
    ttm_from_quarters,
)
from app.utils.technical_indicators import (
    AdjustedPricePoint,
    calculate_technical_snapshot,
)
from tests.helpers import make_settings, migrate_database


def test_cumulative_financial_values_become_standalone_quarters() -> None:
    assert cumulative_to_quarters(
        [
            Decimal(100),
            Decimal(220),
            Decimal(360),
            Decimal(500),
        ]
    ) == (
        Decimal(100),
        Decimal(120),
        Decimal(140),
        Decimal(140),
    )


def test_ttm_is_missing_if_any_quarter_is_missing() -> None:
    assert ttm_from_quarters(
        [Decimal(100), Decimal(120), None, Decimal(140)]
    ) is None
    assert ttm_from_quarters(
        [Decimal(100), Decimal(120), Decimal(140), Decimal(140)]
    ) == Decimal(500)
    assert ttm_from_annual_and_interim(
        prior_annual=Decimal(500),
        current_cumulative=Decimal(360),
        prior_cumulative=Decimal(330),
    ) == Decimal(530)
    assert (
        ttm_from_annual_and_interim(
            prior_annual=Decimal(500),
            current_cumulative=None,
            prior_cumulative=Decimal(330),
        )
        is None
    )


def test_xbrl_mapping_does_not_turn_unknown_account_into_zero() -> None:
    assert map_xbrl_account("ifrs-full_Revenue") == "REVENUE"
    assert map_xbrl_account("entity-extension_UnverifiedProfit") is None
    assert (
        map_xbrl_account(
            "ifrs-full_ProfitLoss",
            "지배기업 소유주지분 [member]",
        )
        is None
    )


def test_dividend_parser_only_accepts_explicit_unit_label() -> None:
    parsed = parse_confirmed_dividend_fact(
        label="주당 현금배당금(원)",
        raw_value="2,500",
    )
    assert parsed == (Decimal(2500), "KRW")
    assert (
        parse_confirmed_dividend_fact(
            label="주당 현금배당금",
            raw_value="2,500",
        )
        is None
    )


def test_dividend_upsert_deduplicates_and_keeps_informative_fact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(
        tmp_path / "duplicate-dividend-facts.db",
        monkeypatch,
    )
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    collected_at = now_kst()
    common = {
        "rcept_no": "20220805000318",
        "corp_cls": "Y",
        "corp_code": "00126380",
        "corp_name": "분석검증",
        "se": "주당 현금배당금(원)",
        "stock_knd": "-",
        "stlm_dt": "2021-12-31",
    }
    records = [
        DartDividendFactItem.model_validate(
            {
                **common,
                "thstrm": "270",
                "frmtrm": "210",
                "lwfr": "300",
            }
        ),
        DartDividendFactItem.model_validate(
            {
                **common,
                "thstrm": "-",
                "frmtrm": "-",
                "lwfr": "-",
            }
        ),
    ]

    with sessions.begin() as session:
        stock = _stock(collected_at)
        session.add(stock)
        session.flush()
        disclosure = Disclosure(
            stock_id=stock.id,
            corp_code="00126380",
            receipt_no=common["rcept_no"],
            report_name="사업보고서",
            receipt_date=date(2022, 8, 5),
            source_url=common["rcept_no"],
            is_correction=False,
            source_provider="OpenDART",
            source_function="공시검색",
            data_state=DataState.AVAILABLE.value,
            collected_at=collected_at,
            data_timing=DataTiming.PERIODIC_DISCLOSURE.value,
        )
        session.add(disclosure)
        session.flush()
        fact_count, dividend_count = FinancialRepository().upsert_dividends(
            session,
            stock=stock,
            business_year=2021,
            records=records,
            disclosures={common["rcept_no"]: disclosure},
            raw_response_id=None,
            collected_at=collected_at,
        )

    with sessions() as session:
        fact = session.query(DividendFact).one()
        dividend = session.query(Dividend).one()
        assert fact.current_raw == "270"
        assert dividend.dps == Decimal(270)
    engine.dispose()

    assert fact_count == 1
    assert dividend_count == 1


def test_dart_no_data_is_not_available_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={"status": "013", "message": "조회된 데이타가 없습니다."},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenDartAnalysisProvider(
        make_settings(dart_api_key="test-key"),
        client,
    )
    response = asyncio.run(
        provider.fetch_financials(
            corp_code="00126380",
            business_year=2025,
            report_code="11011",
            scope=FinancialScope.CONSOLIDATED,
        )
    )
    asyncio.run(client.aclose())

    assert response.state == DataState.MISSING
    assert response.payload is None
    assert response.error_code == "013"


def test_dart_financial_contract_preserves_current_and_cumulative_amounts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["corp_code"] == "00126380"
        assert request.url.params["fs_div"] == "CFS"
        return httpx.Response(
            200,
            request=request,
            json={
                "status": "000",
                "message": "정상",
                "list": [
                    {
                        "rcept_no": "20260515001234",
                        "reprt_code": "11013",
                        "bsns_year": "2026",
                        "corp_code": "00126380",
                        "sj_div": "IS",
                        "sj_nm": "연결손익계산서",
                        "account_id": "ifrs-full_Revenue",
                        "account_nm": "매출액",
                        "account_detail": "",
                        "thstrm_nm": "제 58 기 1분기",
                        "thstrm_amount": "10,000",
                        "thstrm_add_amount": "10,000",
                        "frmtrm_nm": "제 57 기",
                        "frmtrm_amount": "9,000",
                        "frmtrm_q_nm": "제 57 기 1분기",
                        "frmtrm_q_amount": "9,000",
                        "frmtrm_add_amount": "9,000",
                        "bfefrmtrm_nm": "",
                        "bfefrmtrm_amount": "",
                        "ord": "1",
                        "currency": "KRW",
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenDartAnalysisProvider(
        make_settings(dart_api_key="test-key"),
        client,
    )
    response = asyncio.run(
        provider.fetch_financials(
            corp_code="00126380",
            business_year=2026,
            report_code="11013",
            scope=FinancialScope.CONSOLIDATED,
        )
    )
    asyncio.run(client.aclose())

    assert response.state == DataState.AVAILABLE
    assert response.payload is not None
    assert response.payload[0].current_amount == Decimal(10000)
    assert response.payload[0].current_cumulative_amount == Decimal(10000)


def test_dart_financial_contract_rejects_different_request_context() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "status": "000",
                "message": "정상",
                "list": [
                    {
                        "rcept_no": "20260515001234",
                        "reprt_code": "11013",
                        "bsns_year": "2025",
                        "corp_code": "00126380",
                        "sj_div": "IS",
                        "sj_nm": "연결손익계산서",
                        "account_id": "ifrs-full_Revenue",
                        "account_nm": "매출액",
                        "account_detail": "",
                        "thstrm_nm": "제 58 기 1분기",
                        "thstrm_amount": "10,000",
                        "thstrm_add_amount": "10,000",
                        "frmtrm_nm": "제 57 기",
                        "frmtrm_amount": "9,000",
                        "ord": "1",
                        "currency": "KRW",
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenDartAnalysisProvider(
        make_settings(dart_api_key="test-key"),
        client,
    )
    response = asyncio.run(
        provider.fetch_financials(
            corp_code="00126380",
            business_year=2026,
            report_code="11013",
            scope=FinancialScope.CONSOLIDATED,
        )
    )
    asyncio.run(client.aclose())

    assert response.state == DataState.FETCH_FAILED
    assert response.error_code == "SCHEMA_VALIDATION_FAILED"


def test_dart_disclosure_contract_rejects_future_receipt_date() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "status": "000",
                "message": "정상",
                "page_no": 1,
                "page_count": 100,
                "total_count": 1,
                "total_page": 1,
                "list": [
                    {
                        "corp_cls": "Y",
                        "corp_name": "분석검증",
                        "corp_code": "00126380",
                        "stock_code": "000001",
                        "report_nm": "분기보고서",
                        "rcept_no": "20260730000001",
                        "flr_nm": "분석검증",
                        "rcept_dt": "20260730",
                        "rm": "",
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenDartAnalysisProvider(
        make_settings(dart_api_key="test-key"),
        client,
    )
    response = asyncio.run(
        provider.fetch_disclosures(
            corp_code="00126380",
            begin_date=date(2026, 1, 1),
            end_date=date(2026, 7, 29),
        )
    )
    asyncio.run(client.aclose())

    assert response.state == DataState.FETCH_FAILED
    assert response.error_code == "SCHEMA_VALIDATION_FAILED"


def test_dart_dividend_contract_rejects_different_corporation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "status": "000",
                "message": "정상",
                "list": [
                    {
                        "rcept_no": "20260331000001",
                        "corp_cls": "Y",
                        "corp_code": "00999999",
                        "corp_name": "다른회사",
                        "se": "주당 현금배당금(원)",
                        "stock_knd": "보통주",
                        "thstrm": "1,000",
                        "frmtrm": "900",
                        "lwfr": "800",
                        "stlm_dt": "2025-12-31",
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenDartAnalysisProvider(
        make_settings(dart_api_key="test-key"),
        client,
    )
    response = asyncio.run(
        provider.fetch_dividends(
            corp_code="00126380",
            business_year=2025,
        )
    )
    asyncio.run(client.aclose())

    assert response.state == DataState.FETCH_FAILED
    assert response.error_code == "SCHEMA_VALIDATION_FAILED"


def test_dart_dividend_contract_rejects_different_business_year() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "status": "000",
                "message": "정상",
                "list": [
                    {
                        "rcept_no": "20260331000001",
                        "corp_cls": "Y",
                        "corp_code": "00126380",
                        "corp_name": "분석검증",
                        "se": "주당 현금배당금(원)",
                        "stock_knd": "보통주",
                        "thstrm": "1,000",
                        "frmtrm": "900",
                        "lwfr": "800",
                        "stlm_dt": "2026-12-31",
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenDartAnalysisProvider(
        make_settings(dart_api_key="test-key"),
        client,
    )
    response = asyncio.run(
        provider.fetch_dividends(
            corp_code="00126380",
            business_year=2025,
        )
    )
    asyncio.run(client.aclose())

    assert response.state == DataState.FETCH_FAILED
    assert response.error_code == "SCHEMA_VALIDATION_FAILED"


def test_dart_audit_contract_rejects_future_business_year() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "status": "000",
                "message": "정상",
                "list": [
                    {
                        "rcept_no": "20260331000001",
                        "corp_cls": "Y",
                        "corp_code": "00126380",
                        "corp_name": "분석검증",
                        "bsns_year": "2026",
                        "adtor": "검증회계법인",
                        "adt_opinion": "적정",
                        "adt_reprt_spcmnt_matter": "",
                        "emphs_matter": "",
                        "core_adt_matter": "",
                        "stlm_dt": "2026-12-31",
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenDartAnalysisProvider(
        make_settings(dart_api_key="test-key"),
        client,
    )
    response = asyncio.run(
        provider.fetch_audit_opinions(
            corp_code="00126380",
            business_year=2025,
        )
    )
    asyncio.run(client.aclose())

    assert response.state == DataState.FETCH_FAILED
    assert response.error_code == "SCHEMA_VALIDATION_FAILED"


def test_dart_financial_account_accepts_omitted_optional_amounts() -> None:
    item = DartFinancialAccountItem.model_validate(
        {
            "rcept_no": "20260331000001",
            "reprt_code": "11011",
            "bsns_year": "2025",
            "corp_code": "00126380",
            "sj_div": "BS",
            "sj_nm": "재무상태표",
            "account_nm": "자산총계",
            "thstrm_nm": "제57기",
            "frmtrm_nm": "제56기",
            "ord": "1",
        }
    )

    assert item.current_amount is None
    assert item.current_cumulative_amount is None
    assert item.prior_amount is None
    assert item.currency is None


def test_dart_audit_uses_fiscal_date_for_business_year() -> None:
    item = DartAuditOpinionItem.model_validate(
        {
            "rcept_no": "20260331000001",
            "corp_cls": "Y",
            "corp_code": "00126380",
            "corp_name": "삼성전자",
            "bsns_year": "제57기 \n(당기)",
            "adtor": "삼일회계법인",
            "adt_opinion": "적정",
            "stlm_dt": "2025-12-31",
        }
    )

    assert item.business_year_label == "제57기 \n(당기)"
    assert item.business_year == 2025


def test_dart_company_profile_requires_official_industry_code() -> None:
    item = DartCompanyProfileItem.model_validate(
        {
            "corp_code": "00126380",
            "corp_name": "삼성전자",
            "stock_code": "005930",
            "induty_code": "264",
        }
    )

    assert item.industry_code == "264"


def test_official_disclosure_modification_prefixes_are_preserved() -> None:
    item = DartDisclosureItem.model_validate(
        {
            "corp_cls": "Y",
            "corp_name": "분석검증",
            "corp_code": "00126380",
            "stock_code": "000001",
            "report_nm": "[변경등록]분기보고서",
            "rcept_no": "20260729000001",
            "flr_nm": "분석검증",
            "rcept_dt": "20260729",
            "rm": "",
        }
    )

    assert item.is_correction is True


def _stock(collected_at: datetime) -> Stock:
    return Stock(
        symbol="000001",
        name_ko="분석검증",
        dart_corp_code="00126380",
        listing_status="LISTED",
        universe_status="REVIEW_REQUIRED",
        quality_state="VALID",
        dart_data_state="AVAILABLE",
        is_active=True,
        source_provider="KRX",
        source_function="유가증권 종목기본정보",
        data_state="AVAILABLE",
        as_of_at=collected_at,
        collected_at=collected_at,
        data_timing="NOT_APPLICABLE",
    )


def test_financial_query_always_prefers_consolidated_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "scope.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    collected_at = now_kst()
    with sessions.begin() as session:
        stock = _stock(collected_at)
        session.add(stock)
        session.flush()
        for scope, receipt, filing_date, amount in (
            ("CFS", "20260331000001", date(2026, 3, 31), Decimal(100)),
            ("OFS", "20260401000001", date(2026, 4, 1), Decimal(999)),
        ):
            statement = FinancialStatement(
                stock_id=stock.id,
                corp_code="00126380",
                receipt_no=receipt,
                report_code="11011",
                business_year=2025,
                statement_kind="IS",
                fs_div=scope,
                filing_date=filing_date,
                source_provider="OpenDART",
                source_function="단일회사 전체 재무제표",
                data_state="AVAILABLE",
                collected_at=collected_at,
                data_timing="PERIODIC_DISCLOSURE",
            )
            session.add(statement)
            session.flush()
            session.add(
                FinancialAccount(
                    statement_id=statement.id,
                    account_id="ifrs-full_Revenue",
                    account_name="매출액",
                    current_amount=amount,
                    amount=amount,
                    unit="KRW",
                    canonical_metric_code="REVENUE",
                    mapping_status="MAPPED",
                )
            )
        stock_id = stock.id
    with sessions() as session:
        scope, accounts = FinancialRepository().latest_mapped_accounts(
            session,
            stock_id,
        )
    engine.dispose()

    assert scope == FinancialScope.CONSOLIDATED
    assert accounts[0].value == Decimal(100)


def test_financial_query_uses_newer_separate_report_when_cfs_is_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "scope-by-period.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    collected_at = now_kst()
    with sessions.begin() as session:
        stock = _stock(collected_at)
        session.add(stock)
        session.flush()
        for year, report_code, scope, receipt, filing_date, amount in (
            (
                2025,
                "11011",
                "CFS",
                "20260331000001",
                date(2026, 3, 31),
                Decimal(100),
            ),
            (
                2026,
                "11013",
                "OFS",
                "20260515000001",
                date(2026, 5, 15),
                Decimal(200),
            ),
        ):
            statement = FinancialStatement(
                stock_id=stock.id,
                corp_code="00126380",
                receipt_no=receipt,
                report_code=report_code,
                business_year=year,
                statement_kind="IS",
                fs_div=scope,
                filing_date=filing_date,
                source_provider="OpenDART",
                source_function="단일회사 전체 재무제표",
                data_state="AVAILABLE",
                collected_at=collected_at,
                data_timing="PERIODIC_DISCLOSURE",
            )
            session.add(statement)
            session.flush()
            session.add(
                FinancialAccount(
                    statement_id=statement.id,
                    account_id="ifrs-full_Revenue",
                    account_name="매출액",
                    current_amount=amount,
                    current_cumulative_amount=amount,
                    amount=amount,
                    unit="KRW",
                    canonical_metric_code="REVENUE",
                    mapping_status="MAPPED",
                )
            )
        stock_id = stock.id
    with sessions() as session:
        scope, accounts = FinancialRepository().latest_mapped_accounts(
            session,
            stock_id,
        )
    engine.dispose()

    assert scope == FinancialScope.SEPARATE
    assert accounts[0].business_year == 2026
    assert accounts[0].value == Decimal(200)


def test_financial_repository_creates_complete_statement_before_flush(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(
        tmp_path / "new-financial-statement.db",
        monkeypatch,
    )
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    collected_at = now_kst()
    record = DartFinancialAccountItem.model_validate(
        {
            "rcept_no": "20260331000001",
            "reprt_code": "11011",
            "bsns_year": "2025",
            "corp_code": "00126380",
            "sj_div": "IS",
            "sj_nm": "연결손익계산서",
            "account_id": "ifrs-full_Revenue",
            "account_nm": "매출액",
            "account_detail": "",
            "thstrm_nm": "제 1 기",
            "thstrm_amount": "1,000",
            "thstrm_add_amount": "1,000",
            "frmtrm_nm": "제 0 기",
            "frmtrm_amount": "900",
            "ord": "1",
            "currency": "KRW",
        }
    )
    with sessions.begin() as session:
        stock = _stock(collected_at)
        session.add(stock)
        session.flush()
        disclosure = Disclosure(
            stock_id=stock.id,
            corp_code="00126380",
            receipt_no=record.receipt_no,
            report_name="사업보고서",
            receipt_date=date(2026, 3, 31),
            source_url=record.receipt_no,
            is_correction=False,
            source_provider="OpenDART",
            source_function="공시검색",
            data_state=DataState.AVAILABLE.value,
            collected_at=collected_at,
            data_timing=DataTiming.PERIODIC_DISCLOSURE.value,
        )
        session.add(disclosure)
        session.flush()

        statements, accounts = FinancialRepository().upsert_financial_accounts(
            session,
            stock=stock,
            records=[record],
            scope=FinancialScope.CONSOLIDATED,
            disclosure=disclosure,
            raw_response_id=None,
            collected_at=collected_at,
        )

    with sessions() as session:
        statement = session.query(FinancialStatement).one()
        assert statement.corp_code == "00126380"
        assert statement.report_code == "11011"
        assert statement.filing_date == date(2026, 3, 31)
    engine.dispose()

    assert statements == 1
    assert accounts == 1


def _metadata(
    state: DataState,
    function_name: str,
    scope: FinancialScope = FinancialScope.NOT_APPLICABLE,
) -> DataMetadata:
    return DataMetadata(
        provider="OpenDART",
        function_name=function_name,
        state=state,
        collected_at=now_kst(),
        timing=DataTiming.PERIODIC_DISCLOSURE,
        financial_scope=scope,
    )


def _missing_response(function_name: str) -> ApiResponse[object]:
    return ApiResponse(
        state=DataState.MISSING,
        metadata=_metadata(DataState.MISSING, function_name),
        http_status=200,
        content_type="application/json",
        raw_content=b'{"status":"013"}',
        error_code="013",
        error_message="조회된 데이터 없음",
    )


def _available_response[PayloadT](
    function_name: str,
    payload: PayloadT,
    *,
    raw_content: bytes,
    scope: FinancialScope = FinancialScope.NOT_APPLICABLE,
) -> ApiResponse[PayloadT]:
    return ApiResponse(
        state=DataState.AVAILABLE,
        metadata=_metadata(DataState.AVAILABLE, function_name, scope),
        payload=payload,
        http_status=200,
        content_type="application/json",
        raw_content=raw_content,
    )


class _UnmatchedReceiptProvider:
    async def fetch_company_profile(self, **_: object) -> ApiResponse[object]:
        return _missing_response("기업개황")

    async def fetch_disclosures(self, **_: object) -> ApiResponse[object]:
        return _missing_response("공시검색")

    async def fetch_audit_opinions(
        self,
        **_: object,
    ) -> ApiResponse[list[DartAuditOpinionItem]]:
        item = DartAuditOpinionItem.model_validate(
            {
                "rcept_no": "20260331000001",
                "corp_cls": "Y",
                "corp_code": "00126380",
                "corp_name": "분석검증",
                "bsns_year": "2026",
                "adtor": "검증회계법인",
                "adt_opinion": "적정",
                "adt_reprt_spcmnt_matter": "",
                "emphs_matter": "",
                "core_adt_matter": "",
                "stlm_dt": "2026-12-31",
            }
        )
        return _available_response(
            "회계감사인의 명칭 및 감사의견",
            [item],
            raw_content=b'{"status":"000","kind":"audit"}',
        )

    async def fetch_dividends(
        self,
        *,
        report_code: str,
        **_: object,
    ) -> ApiResponse[list[DartDividendFactItem]]:
        if report_code != "11011":
            return _missing_response("배당에 관한 사항")  # type: ignore[return-value]
        item = DartDividendFactItem.model_validate(
            {
                "rcept_no": "20260331000002",
                "corp_cls": "Y",
                "corp_code": "00126380",
                "corp_name": "분석검증",
                "se": "주당 현금배당금(원)",
                "stock_knd": "보통주",
                "thstrm": "1,000",
                "frmtrm": "900",
                "lwfr": "800",
                "stlm_dt": "2026-12-31",
            }
        )
        return _available_response(
            "배당에 관한 사항",
            [item],
            raw_content=b'{"status":"000","kind":"dividend"}',
        )

    async def fetch_financials(
        self,
        *,
        report_code: str,
        scope: FinancialScope,
        **_: object,
    ) -> ApiResponse[list[DartFinancialAccountItem]]:
        if report_code != "11011" or scope != FinancialScope.CONSOLIDATED:
            return _missing_response("단일회사 전체 재무제표")  # type: ignore[return-value]
        item = DartFinancialAccountItem.model_validate(
            {
                "rcept_no": "20260331000003",
                "reprt_code": "11011",
                "bsns_year": "2026",
                "corp_code": "00126380",
                "sj_div": "IS",
                "sj_nm": "연결손익계산서",
                "account_id": "ifrs-full_Revenue",
                "account_nm": "매출액",
                "account_detail": "",
                "thstrm_nm": "제 1 기",
                "thstrm_amount": "1,000",
                "thstrm_add_amount": "1,000",
                "frmtrm_nm": "제 0 기",
                "frmtrm_amount": "900",
                "frmtrm_q_nm": "",
                "frmtrm_q_amount": "",
                "frmtrm_add_amount": "900",
                "bfefrmtrm_nm": "",
                "bfefrmtrm_amount": "",
                "ord": "1",
                "currency": "KRW",
            }
        )
        return _available_response(
            "단일회사 전체 재무제표",
            [item],
            raw_content=b'{"status":"000","kind":"financial"}',
            scope=scope,
        )


class _RecordingMissingProvider:
    def __init__(self) -> None:
        self.audit_years: list[int] = []
        self.dividend_years: list[int] = []
        self.dividend_requests: list[tuple[int, str]] = []
        self.financial_years: list[int] = []
        self.financial_requests: list[tuple[int, str, FinancialScope]] = []

    async def fetch_company_profile(self, **_: object) -> ApiResponse[object]:
        return _missing_response("기업개황")

    async def fetch_disclosures(self, **_: object) -> ApiResponse[object]:
        return _missing_response("공시검색")

    async def fetch_audit_opinions(
        self,
        *,
        business_year: int,
        **_: object,
    ) -> ApiResponse[object]:
        self.audit_years.append(business_year)
        return _missing_response("회계감사인의 명칭 및 감사의견")

    async def fetch_dividends(
        self,
        *,
        business_year: int,
        report_code: str,
        **_: object,
    ) -> ApiResponse[object]:
        self.dividend_requests.append((business_year, report_code))
        if report_code == "11011":
            self.dividend_years.append(business_year)
        return _missing_response("배당에 관한 사항")

    async def fetch_financials(
        self,
        *,
        business_year: int,
        report_code: str,
        scope: FinancialScope,
        **_: object,
    ) -> ApiResponse[object]:
        self.financial_years.append(business_year)
        self.financial_requests.append((business_year, report_code, scope))
        return _missing_response("단일회사 전체 재무제표")


def test_incremental_report_plan_uses_only_filed_periods() -> None:
    as_of_date = date(2026, 7, 31)

    assert _incremental_report_codes(
        2025,
        as_of_date,
        include_all_interims=False,
    ) == ("11011",)
    assert _incremental_report_codes(
        2026,
        as_of_date,
        include_all_interims=False,
    ) == ("11013",)
    assert _incremental_report_codes(
        2026,
        as_of_date,
        include_all_interims=True,
    ) == ("11013",)


def test_incremental_refresh_skips_historical_quarterly_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(
        tmp_path / "incremental-window.db",
        monkeypatch,
    )
    settings = make_settings(
        database_url=database_url,
        raw_data_dir=tmp_path / "raw",
    )
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        session.add(_stock(now_kst()))
    engine.dispose()
    provider = _RecordingMissingProvider()

    service = StockAnalysisService(
        settings,
        provider=provider,  # type: ignore[arg-type]
    )
    asyncio.run(
        service.refresh(
            symbol="000001",
            as_of_date=date(2026, 7, 31),
            years=3,
            incremental=True,
        )
    )
    service.close()

    assert provider.audit_years == [2023, 2024, 2025]
    assert provider.dividend_requests == [
        (2023, "11011"),
        (2024, "11011"),
        (2025, "11011"),
        (2026, "11013"),
    ]
    assert provider.financial_requests == [
        (year, report_code, scope)
        for year, report_code in (
            (2024, "11011"),
            (2025, "11011"),
            (2026, "11013"),
        )
        for scope in (FinancialScope.CONSOLIDATED, FinancialScope.SEPARATE)
    ]


def test_five_year_dividend_request_includes_prior_completed_year_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(
        tmp_path / "five-year-window.db",
        monkeypatch,
    )
    settings = make_settings(
        database_url=database_url,
        raw_data_dir=tmp_path / "raw",
    )
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        session.add(_stock(now_kst()))
    engine.dispose()
    provider = _RecordingMissingProvider()

    service = StockAnalysisService(
        settings,
        provider=provider,  # type: ignore[arg-type]
    )
    asyncio.run(
        service.refresh(
            symbol="000001",
            as_of_date=date(2026, 7, 29),
            years=5,
        )
    )
    service.close()

    assert provider.audit_years == [2021, 2022, 2023, 2024, 2025, 2026]
    assert provider.dividend_years == [2021, 2022, 2023, 2024, 2025, 2026]
    assert provider.dividend_requests == [
        (year, report_code)
        for year in range(2021, 2027)
        for report_code in ("11011", "11012", "11013", "11014")
    ]
    assert min(provider.financial_years) == 2022


def test_future_filing_dates_block_all_normalized_dart_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(
        tmp_path / "missing-filing-date.db",
        monkeypatch,
    )
    settings = make_settings(
        database_url=database_url,
        raw_data_dir=tmp_path / "raw",
    )
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        collected_at = now_kst()
        stock = _stock(collected_at)
        session.add(stock)
        session.flush()
        for receipt_no in (
            "20260331000001",
            "20260331000002",
            "20260331000003",
        ):
            session.add(
                Disclosure(
                    stock_id=stock.id,
                    corp_code="00126380",
                    receipt_no=receipt_no,
                    report_name="미래 제출 보고서",
                    receipt_date=date(2026, 8, 1),
                    source_url=(
                        "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="
                        f"{receipt_no}"
                    ),
                    is_correction=False,
                    source_provider="OpenDART",
                    source_function="공시검색",
                    data_state=DataState.AVAILABLE.value,
                    collected_at=collected_at,
                    data_timing=DataTiming.PERIODIC_DISCLOSURE.value,
                )
            )
    engine.dispose()

    service = StockAnalysisService(
        settings,
        provider=_UnmatchedReceiptProvider(),  # type: ignore[arg-type]
    )
    summary = asyncio.run(
        service.refresh(
            symbol="000001",
            as_of_date=date(2026, 7, 29),
            years=1,
        )
    )
    service.close()

    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions() as session:
        assert session.query(FinancialStatement).count() == 0
        assert session.query(DividendFact).count() == 0
        assert session.query(Dividend).count() == 0
        assert session.query(AuditOpinion).count() == 0
        available_raw = (
            session.query(ApiRawResponse)
            .filter(ApiRawResponse.data_state == DataState.AVAILABLE.value)
            .all()
        )
        assert len(available_raw) == 5
        assert all(row.normalized_success is False for row in available_raw)
        assert all(
            row.error_code == "MISSING_FILING_DATE"
            for row in available_raw
        )

    assert summary.state == DataState.MISSING.value

    with sessions.begin() as session:
        for disclosure in session.query(Disclosure).all():
            disclosure.receipt_date = date(2026, 7, 28)
    engine.dispose()

    retry_service = StockAnalysisService(
        settings,
        provider=_UnmatchedReceiptProvider(),  # type: ignore[arg-type]
    )
    retry_summary = asyncio.run(
        retry_service.refresh(
            symbol="000001",
            as_of_date=date(2026, 7, 29),
            years=1,
        )
    )
    retry_service.close()

    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions() as session:
        retried_raw = (
            session.query(ApiRawResponse)
            .filter(ApiRawResponse.data_state == DataState.AVAILABLE.value)
            .all()
        )
        assert all(row.normalized_success is True for row in retried_raw)
        assert all(row.error_code is None for row in retried_raw)
        assert session.query(FinancialStatement).count() == 1
        assert session.query(Dividend).count() == 2
        assert session.query(AuditOpinion).count() == 1
    engine.dispose()

    assert retry_summary.state == DataState.AVAILABLE.value


def test_analysis_refresh_without_key_stores_no_false_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "no-key.db", monkeypatch)
    settings = make_settings(
        database_url=database_url,
        raw_data_dir=tmp_path / "raw",
    )
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        session.add(_stock(now_kst()))
    engine.dispose()

    service = StockAnalysisService(settings)
    summary = asyncio.run(
        service.refresh(
            symbol="000001",
            as_of_date=date(2026, 7, 29),
            years=5,
        )
    )
    service.close()

    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions() as session:
        assert session.query(ApiRawResponse).count() == 0
        assert session.query(FinancialStatement).count() == 0
    engine.dispose()
    assert summary.state == DataState.NOT_CONFIGURED.value


def _price_points(*, verified: bool, count: int = 252) -> list[AdjustedPricePoint]:
    return [
        AdjustedPricePoint(
            trade_date=date.fromordinal(date(2025, 1, 1).toordinal() + index),
            high=Decimal(index + 11),
            low=Decimal(index + 9),
            close=Decimal(index + 10),
            is_adjusted=True if verified else None,
            adjustment_status="VERIFIED" if verified else "NOT_VERIFIED",
            source_provider="VERIFIED_SOURCE",
        )
        for index in range(count)
    ]


def test_technical_indicators_require_verified_adjusted_prices() -> None:
    snapshot = calculate_technical_snapshot(_price_points(verified=False))

    assert snapshot.state == DataState.NOT_VERIFIED
    assert snapshot.rsi_14 is None
    assert snapshot.sma_200 is None


def test_technical_indicators_reject_mixed_price_sources() -> None:
    points = _price_points(verified=True)
    points[-1] = AdjustedPricePoint(
        trade_date=points[-1].trade_date,
        high=points[-1].high,
        low=points[-1].low,
        close=points[-1].close,
        is_adjusted=True,
        adjustment_status="VERIFIED",
        source_provider="SECOND_SOURCE",
    )
    points[-2] = AdjustedPricePoint(
        trade_date=points[-2].trade_date,
        high=points[-2].high,
        low=points[-2].low,
        close=points[-2].close,
        is_adjusted=True,
        adjustment_status="VERIFIED",
        source_provider="FIRST_SOURCE",
    )

    snapshot = calculate_technical_snapshot(points)

    assert snapshot.state == DataState.CONFLICT
    assert snapshot.rsi_14 is None
    assert "단일 가격 원천" in (snapshot.error_message or "")


def test_wilder_rsi_sma_atr_and_52_week_drawdown() -> None:
    snapshot = calculate_technical_snapshot(_price_points(verified=True))

    assert snapshot.state == DataState.AVAILABLE
    assert snapshot.rsi_14 == Decimal(100)
    assert snapshot.sma_20 == Decimal("251.5")
    assert snapshot.sma_200 == Decimal("161.5")
    assert snapshot.atr_14 == Decimal(2)
    assert snapshot.drawdown_52_week == Decimal(261) / Decimal(262) - Decimal(1)
