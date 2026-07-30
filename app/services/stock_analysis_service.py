from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models.disclosure import Disclosure
from app.db.models.market import Stock
from app.db.session import create_db_engine, create_session_factory
from app.models.financial import (
    DartDisclosurePage,
    FinancialRefreshSummary,
    StockAnalysisSnapshot,
)
from app.models.metadata import DataState, FinancialScope
from app.providers.base import ApiResponse
from app.providers.dart_analysis import (
    DART_AUDIT_ENDPOINT,
    DART_AUDIT_FUNCTION,
    DART_DISCLOSURE_ENDPOINT,
    DART_DISCLOSURE_FUNCTION,
    DART_DIVIDEND_ENDPOINT,
    DART_DIVIDEND_FUNCTION,
    DART_FINANCIAL_ENDPOINT,
    DART_FINANCIAL_FUNCTION,
    OpenDartAnalysisProvider,
)
from app.repositories.data_quality_repository import DataQualityRepository
from app.repositories.disclosure_repository import DisclosureRepository
from app.repositories.financial_repository import FinancialRepository
from app.repositories.price_repository import PriceRepository
from app.repositories.raw_response_repository import RawResponseRepository
from app.services.account_mapping import map_xbrl_account
from app.utils.dates import now_kst
from app.utils.technical_indicators import calculate_technical_snapshot

_REPORT_CODES = ("11011", "11012", "11013", "11014")


def _is_cash_dividend_decision(report_name: str) -> bool:
    compact = report_name.replace(" ", "")
    return "현금ㆍ현물배당결정" in compact or "현금·현물배당결정" in compact


class StockAnalysisService:
    def __init__(
        self,
        settings: Settings,
        *,
        provider: OpenDartAnalysisProvider | None = None,
    ) -> None:
        self._provider = provider or OpenDartAnalysisProvider(settings)
        self._raw = RawResponseRepository(settings)
        self._quality = DataQualityRepository()
        self._disclosures = DisclosureRepository()
        self._financials = FinancialRepository()
        self._prices = PriceRepository(self._quality)
        self._engine = create_db_engine(settings)
        self._sessions = create_session_factory(self._engine)

    async def refresh(
        self,
        *,
        symbol: str,
        as_of_date: date,
        years: int = 5,
    ) -> FinancialRefreshSummary:
        if years < 1 or years > 5:
            raise ValueError("years must be between 1 and 5")
        started_at = now_kst()
        with self._sessions() as session:
            stock = self._financials.get_stock(session, symbol)
            if stock is None:
                return self._summary(
                    state=DataState.MISSING,
                    symbol=symbol,
                    started_at=started_at,
                    years=years,
                    errors=("종목을 찾을 수 없습니다.",),
                )
            if not stock.dart_corp_code:
                return self._summary(
                    state=DataState.MISSING,
                    symbol=symbol,
                    started_at=started_at,
                    years=years,
                    errors=("OpenDART 고유번호가 매핑되지 않았습니다.",),
                )
            stock_id = stock.id
            corp_code = stock.dart_corp_code

        begin_date = date(as_of_date.year - years - 1, 1, 1)
        disclosures_stored = 0
        errors: list[str] = []
        periodic_state, stored, page_errors = await self._collect_disclosures(
            stock_id=stock_id,
            corp_code=corp_code,
            begin_date=begin_date,
            end_date=as_of_date,
            publication_type="A",
            disclosure_type="PERIODIC",
            predicate=lambda _: True,
        )
        disclosures_stored += stored
        errors.extend(page_errors)
        if periodic_state == DataState.NOT_CONFIGURED:
            return self._summary(
                state=periodic_state,
                symbol=symbol,
                started_at=started_at,
                years=years,
                disclosures_stored=disclosures_stored,
                errors=tuple(errors),
            )

        _, stored, page_errors = await self._collect_disclosures(
            stock_id=stock_id,
            corp_code=corp_code,
            begin_date=begin_date,
            end_date=as_of_date,
            publication_type="I",
            disclosure_type="DIVIDEND_DECISION",
            predicate=lambda item: _is_cash_dividend_decision(item.report_name),
        )
        disclosures_stored += stored
        errors.extend(page_errors)

        with self._sessions() as session:
            stock = session.get(Stock, stock_id)
            if stock is None:
                return self._summary(
                    state=DataState.MISSING,
                    symbol=symbol,
                    started_at=started_at,
                    years=years,
                    errors=("수집 중 종목 레코드가 사라졌습니다.",),
                )
            disclosure_map = self._disclosures.receipt_metadata(
                session,
                stock_id,
                as_of_date=as_of_date,
            )

        statements_stored = 0
        accounts_stored = 0
        dividend_facts_stored = 0
        dividends_stored = 0
        audit_opinions_stored = 0
        used_scopes: set[FinancialScope] = set()
        financial_first_year = max(
            2015,
            as_of_date.year - years + 1,
        )
        annual_first_year = max(2015, financial_first_year - 1)
        for business_year in range(
            annual_first_year,
            as_of_date.year + 1,
        ):
            audit_response = await self._provider.fetch_audit_opinions(
                corp_code=corp_code,
                business_year=business_year,
            )
            audit_raw_id = self._save_raw(
                response=audit_response,
                function_name=DART_AUDIT_FUNCTION,
                endpoint=DART_AUDIT_ENDPOINT,
                request_parameters={
                    "corp_code": corp_code,
                    "bsns_year": str(business_year),
                    "reprt_code": "11011",
                },
            )
            if (
                audit_response.state == DataState.AVAILABLE
                and audit_response.payload is not None
            ):
                missing_receipts = self._missing_disclosure_receipts(
                    audit_response.payload,
                    disclosure_map,
                )
                if missing_receipts:
                    self._reject_missing_filing_dates(
                        raw_response_id=audit_raw_id,
                        entity_type="audit_opinion",
                        receipt_numbers=missing_receipts,
                    )
                    errors.append(
                        "감사의견 접수번호의 공시 제출일을 확인할 수 없어 "
                        "정규화 저장을 중단했습니다."
                    )
                else:
                    with self._sessions.begin() as session:
                        stock = session.get(Stock, stock_id)
                        if stock is not None:
                            audit_opinions_stored += (
                                self._financials.upsert_audit_opinions(
                                    session,
                                    stock=stock,
                                    records=audit_response.payload,
                                    disclosures=disclosure_map,
                                    collected_at=(audit_response.metadata.collected_at),
                                )
                            )
                            self._set_normalization_success(
                                session,
                                raw_response_id=audit_raw_id,
                            )
                        else:
                            self._set_normalization_failure(
                                session,
                                raw_response_id=audit_raw_id,
                                error_code="MISSING_STOCK",
                                error_message="종목 레코드가 없습니다.",
                            )
            elif audit_response.state not in {
                DataState.MISSING,
                DataState.NOT_CONFIGURED,
            }:
                errors.append(
                    audit_response.error_message
                    or f"{business_year} 감사정보 수집 실패"
                )

            dividend_response = await self._provider.fetch_dividends(
                corp_code=corp_code,
                business_year=business_year,
            )
            raw_id = self._save_raw(
                response=dividend_response,
                function_name=DART_DIVIDEND_FUNCTION,
                endpoint=DART_DIVIDEND_ENDPOINT,
                request_parameters={
                    "corp_code": corp_code,
                    "bsns_year": str(business_year),
                    "reprt_code": "11011",
                },
            )
            if (
                dividend_response.state == DataState.AVAILABLE
                and dividend_response.payload is not None
            ):
                missing_receipts = self._missing_disclosure_receipts(
                    dividend_response.payload,
                    disclosure_map,
                )
                if missing_receipts:
                    self._reject_missing_filing_dates(
                        raw_response_id=raw_id,
                        entity_type="dividend",
                        receipt_numbers=missing_receipts,
                    )
                    errors.append(
                        "배당 접수번호의 공시 제출일을 확인할 수 없어 "
                        "정규화 저장을 중단했습니다."
                    )
                else:
                    with self._sessions.begin() as session:
                        stock = session.get(Stock, stock_id)
                        if stock is not None:
                            fact_count, dividend_count = (
                                self._financials.upsert_dividends(
                                    session,
                                    stock=stock,
                                    business_year=business_year,
                                    records=dividend_response.payload,
                                    disclosures=disclosure_map,
                                    raw_response_id=raw_id,
                                    collected_at=(
                                        dividend_response.metadata.collected_at
                                    ),
                                )
                            )
                            dividend_facts_stored += fact_count
                            dividends_stored += dividend_count
                            self._set_normalization_success(
                                session,
                                raw_response_id=raw_id,
                            )
                        else:
                            self._set_normalization_failure(
                                session,
                                raw_response_id=raw_id,
                                error_code="MISSING_STOCK",
                                error_message="종목 레코드가 없습니다.",
                            )
            elif dividend_response.state not in {
                DataState.MISSING,
                DataState.NOT_CONFIGURED,
            }:
                errors.append(
                    dividend_response.error_message
                    or f"{business_year} 배당정보 수집 실패"
                )

            if business_year < financial_first_year:
                continue
            for report_code in _REPORT_CODES:
                (
                    statement_count,
                    account_count,
                    scope,
                    financial_error,
                ) = await self._collect_financial_report(
                    stock_id=stock_id,
                    corp_code=corp_code,
                    business_year=business_year,
                    report_code=report_code,
                    disclosures=disclosure_map,
                )
                statements_stored += statement_count
                accounts_stored += account_count
                if scope is not None:
                    used_scopes.add(scope)
                if financial_error is not None:
                    errors.append(financial_error)

        scope = (
            next(iter(used_scopes)) if len(used_scopes) == 1 else FinancialScope.UNKNOWN
        )
        state = (
            DataState.AVAILABLE
            if any(
                (
                    statements_stored,
                    dividend_facts_stored,
                    audit_opinions_stored,
                )
            )
            else (
                periodic_state
                if periodic_state != DataState.AVAILABLE
                else DataState.MISSING
            )
        )
        return self._summary(
            state=state,
            symbol=symbol,
            started_at=started_at,
            years=years,
            disclosures_stored=disclosures_stored,
            statements_stored=statements_stored,
            accounts_stored=accounts_stored,
            dividend_facts_stored=dividend_facts_stored,
            dividends_stored=dividends_stored,
            audit_opinions_stored=audit_opinions_stored,
            scope=scope,
            errors=tuple(errors),
        )

    def snapshot(self, symbol: str) -> StockAnalysisSnapshot | None:
        with self._sessions() as session:
            stock = self._financials.get_stock(session, symbol)
            if stock is None:
                return None
            scope, accounts = self._financials.latest_mapped_accounts(
                session,
                stock.id,
            )
            dividends = self._financials.dividend_history(
                session,
                stock.id,
            )
            latest_audit = self._financials.latest_audit(session, stock.id)
            decisions = self._disclosures.dividend_decisions(
                session,
                stock.id,
            )
            history = self._prices.history_for_symbol(session, symbol)
        return StockAnalysisSnapshot(
            symbol=symbol,
            financial_scope=scope,
            financial_accounts=accounts,
            dividends=dividends,
            latest_audit=latest_audit,
            dividend_decisions=decisions,
            technical=calculate_technical_snapshot(history),
        )

    def close(self) -> None:
        self._engine.dispose()

    async def _collect_disclosures(
        self,
        *,
        stock_id: int,
        corp_code: str,
        begin_date: date,
        end_date: date,
        publication_type: str,
        disclosure_type: str,
        predicate: Callable[[Any], bool],
    ) -> tuple[DataState, int, list[str]]:
        stored = 0
        errors: list[str] = []
        page_no = 1
        total_pages = 1
        state = DataState.MISSING
        while page_no <= total_pages:
            response = await self._provider.fetch_disclosures(
                corp_code=corp_code,
                begin_date=begin_date,
                end_date=end_date,
                page_no=page_no,
                publication_type=publication_type,
            )
            state = response.state
            raw_id = self._save_raw(
                response=response,
                function_name=DART_DISCLOSURE_FUNCTION,
                endpoint=DART_DISCLOSURE_ENDPOINT,
                request_parameters={
                    "corp_code": corp_code,
                    "bgn_de": begin_date.strftime("%Y%m%d"),
                    "end_de": end_date.strftime("%Y%m%d"),
                    "last_reprt_at": "N",
                    "pblntf_ty": publication_type,
                    "sort": "date",
                    "sort_mth": "desc",
                    "page_no": str(page_no),
                    "page_count": "100",
                },
            )
            if response.state != DataState.AVAILABLE or response.payload is None:
                with self._sessions.begin() as session:
                    self._quality.add(
                        session,
                        entity_type="stock_analysis_refresh",
                        entity_id=corp_code,
                        provider="OpenDART",
                        issue_code=response.state.value,
                        severity=(
                            "WARNING"
                            if response.state == DataState.MISSING
                            else "ERROR"
                        ),
                        data_state=response.state,
                        message=(
                            response.error_message
                            or "OpenDART 공시검색을 사용할 수 없습니다."
                        ),
                        context={
                            "publication_type": publication_type,
                            "page_no": page_no,
                        },
                    )
                if response.state not in {DataState.MISSING}:
                    errors.append(
                        response.error_message
                        or "OpenDART 공시검색을 사용할 수 없습니다."
                    )
                break
            page: DartDisclosurePage = response.payload
            total_pages = page.total_page
            if total_pages < 1 or total_pages > 10_000:
                with self._sessions.begin() as session:
                    self._set_normalization_failure(
                        session,
                        raw_response_id=raw_id,
                        error_code="INVALID_PAGINATION",
                        error_message=("OpenDART 공시검색 페이지 수가 비정상입니다."),
                    )
                errors.append("OpenDART 공시검색 페이지 수가 비정상입니다.")
                state = DataState.FETCH_FAILED
                break
            selected = tuple(item for item in page.items if predicate(item))
            with self._sessions.begin() as session:
                stock = session.get(Stock, stock_id)
                if stock is not None:
                    stored += self._disclosures.upsert(
                        session,
                        stock=stock,
                        items=selected,
                        raw_response_id=raw_id,
                        disclosure_type=disclosure_type,
                        collected_at=response.metadata.collected_at,
                    )
                    self._set_normalization_success(
                        session,
                        raw_response_id=raw_id,
                    )
                else:
                    self._set_normalization_failure(
                        session,
                        raw_response_id=raw_id,
                        error_code="MISSING_STOCK",
                        error_message="종목 레코드가 없습니다.",
                    )
            page_no += 1
        return state, stored, errors

    @staticmethod
    def _missing_disclosure_receipts(
        records: list[Any],
        disclosures: dict[str, Disclosure],
    ) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    str(item.receipt_no)
                    for item in records
                    if str(item.receipt_no) not in disclosures
                }
            )
        )

    def _reject_missing_filing_dates(
        self,
        *,
        raw_response_id: int | None,
        entity_type: str,
        receipt_numbers: tuple[str, ...],
    ) -> None:
        message = (
            "접수번호의 공시 제출일을 공시검색 결과에서 확인할 수 없어 "
            "정규화 저장을 중단했습니다."
        )
        with self._sessions.begin() as session:
            self._set_normalization_failure(
                session,
                raw_response_id=raw_response_id,
                error_code="MISSING_FILING_DATE",
                error_message=message,
            )
            for receipt_no in receipt_numbers:
                self._quality.add(
                    session,
                    entity_type=entity_type,
                    entity_id=receipt_no,
                    provider="OpenDART",
                    issue_code="MISSING_FILING_DATE",
                    severity="ERROR",
                    data_state=DataState.MISSING,
                    message=message,
                )

    def _set_normalization_failure(
        self,
        session: Session,
        *,
        raw_response_id: int | None,
        error_code: str,
        error_message: str,
    ) -> None:
        self._raw.set_normalization_result(
            session,
            raw_response_id,
            success=False,
            error_code=error_code,
            error_message=error_message,
        )

    def _set_normalization_success(
        self,
        session: Session,
        *,
        raw_response_id: int | None,
    ) -> None:
        self._raw.set_normalization_result(
            session,
            raw_response_id,
            success=True,
        )

    async def _collect_financial_report(
        self,
        *,
        stock_id: int,
        corp_code: str,
        business_year: int,
        report_code: str,
        disclosures: dict[str, Disclosure],
    ) -> tuple[int, int, FinancialScope | None, str | None]:
        for scope in (
            FinancialScope.CONSOLIDATED,
            FinancialScope.SEPARATE,
        ):
            response = await self._provider.fetch_financials(
                corp_code=corp_code,
                business_year=business_year,
                report_code=report_code,
                scope=scope,
            )
            raw_id = self._save_raw(
                response=response,
                function_name=DART_FINANCIAL_FUNCTION,
                endpoint=DART_FINANCIAL_ENDPOINT,
                request_parameters={
                    "corp_code": corp_code,
                    "bsns_year": str(business_year),
                    "reprt_code": report_code,
                    "fs_div": scope.value,
                },
            )
            if response.state == DataState.MISSING:
                continue
            if response.state != DataState.AVAILABLE or response.payload is None:
                return (
                    0,
                    0,
                    None,
                    response.error_message
                    or f"{business_year}/{report_code} 재무정보 수집 실패",
                )
            receipt_numbers = {item.receipt_no for item in response.payload}
            if len(receipt_numbers) != 1:
                with self._sessions.begin() as session:
                    self._set_normalization_failure(
                        session,
                        raw_response_id=raw_id,
                        error_code="INCONSISTENT_RECEIPT_NUMBER",
                        error_message=("재무 응답의 접수번호가 일치하지 않습니다."),
                    )
                return 0, 0, None, "재무 응답의 접수번호가 일치하지 않습니다."
            receipt_no = next(iter(receipt_numbers))
            disclosure = disclosures.get(receipt_no)
            if disclosure is None:
                self._reject_missing_filing_dates(
                    raw_response_id=raw_id,
                    entity_type="financial_statement",
                    receipt_numbers=(receipt_no,),
                )
                return (
                    0,
                    0,
                    None,
                    f"{receipt_no}: 공시 제출일 확인 불가",
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
                    return 0, 0, None, "종목 레코드가 없습니다."
                statements, accounts = self._financials.upsert_financial_accounts(
                    session,
                    stock=stock,
                    records=response.payload,
                    scope=scope,
                    disclosure=disclosure,
                    raw_response_id=raw_id,
                    collected_at=response.metadata.collected_at,
                )
                unmapped = sum(
                    map_xbrl_account(
                        item.account_id,
                        item.account_detail,
                    )
                    is None
                    for item in response.payload
                )
                if unmapped:
                    self._quality.add(
                        session,
                        entity_type="financial_statement",
                        entity_id=receipt_no,
                        provider="OpenDART",
                        issue_code="UNMAPPED_XBRL_ACCOUNTS",
                        severity="WARNING",
                        data_state=DataState.NOT_VERIFIED,
                        message=(
                            f"XBRL 계정 {unmapped}건을 핵심 지표에 매핑하지 "
                            "못했으며 0으로 대체하지 않았습니다."
                        ),
                        context={
                            "unmapped_count": unmapped,
                            "total_count": len(response.payload),
                            "financial_scope": scope.value,
                        },
                    )
                self._set_normalization_success(
                    session,
                    raw_response_id=raw_id,
                )
            return statements, accounts, scope, None
        return 0, 0, None, None

    def _save_raw(
        self,
        *,
        response: ApiResponse[Any],
        function_name: str,
        endpoint: str,
        request_parameters: dict[str, object],
    ) -> int | None:
        with self._sessions.begin() as session:
            row = self._raw.save(
                session,
                provider="OpenDART",
                function_name=function_name,
                endpoint=endpoint,
                request_parameters=request_parameters,
                response=response,
            )
            session.flush()
            return row.id if row is not None else None

    @staticmethod
    def _summary(
        *,
        state: DataState,
        symbol: str,
        started_at: datetime,
        years: int,
        disclosures_stored: int = 0,
        statements_stored: int = 0,
        accounts_stored: int = 0,
        dividend_facts_stored: int = 0,
        dividends_stored: int = 0,
        audit_opinions_stored: int = 0,
        scope: FinancialScope = FinancialScope.UNKNOWN,
        errors: tuple[str, ...] = (),
    ) -> FinancialRefreshSummary:
        return FinancialRefreshSummary(
            state=state.value,
            symbol=symbol,
            started_at=started_at,
            finished_at=now_kst(),
            requested_years=years,
            disclosures_stored=disclosures_stored,
            statements_stored=statements_stored,
            accounts_stored=accounts_stored,
            dividend_facts_stored=dividend_facts_stored,
            dividends_stored=dividends_stored,
            audit_opinions_stored=audit_opinions_stored,
            financial_scope=scope,
            errors=errors,
        )
