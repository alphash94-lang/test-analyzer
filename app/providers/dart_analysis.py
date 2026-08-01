from __future__ import annotations

import json
import re
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date, datetime
from hashlib import sha256
from typing import Any, TypedDict, Unpack

import httpx
from pydantic import HttpUrl, ValidationError

from app.config import Settings
from app.models.financial import (
    DartAuditOpinionItem,
    DartCompanyProfileItem,
    DartDisclosureItem,
    DartDisclosurePage,
    DartDividendFactItem,
    DartFinancialAccountItem,
)
from app.models.metadata import (
    DataMetadata,
    DataState,
    DataTiming,
    FinancialScope,
)
from app.models.status import ConnectionState, ConnectionStatusItem
from app.providers.base import ApiResponse
from app.utils.dates import now_kst
from app.utils.http import AsyncRateLimiter, request_with_retry

DART_DISCLOSURE_ENDPOINT = "https://opendart.fss.or.kr/api/list.json"
DART_FINANCIAL_ENDPOINT = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
DART_DIVIDEND_ENDPOINT = "https://opendart.fss.or.kr/api/alotMatter.json"
DART_AUDIT_ENDPOINT = "https://opendart.fss.or.kr/api/accnutAdtorNmNdAdtOpinion.json"
DART_COMPANY_ENDPOINT = "https://opendart.fss.or.kr/api/company.json"

DART_DISCLOSURE_FUNCTION = "공시검색"
DART_FINANCIAL_FUNCTION = "단일회사 전체 재무제표"
DART_DIVIDEND_FUNCTION = "배당에 관한 사항"
DART_AUDIT_FUNCTION = "회계감사인의 명칭 및 감사의견"
DART_COMPANY_FUNCTION = "기업개황"

_CORP_CODE = re.compile(r"^\d{8}$")
_REPORT_CODES = {"11011", "11012", "11013", "11014"}


class _ResponseDetails(TypedDict):
    http_status: int
    response_hash: str
    content_type: str | None
    raw_content: bytes


def _require_corp_code(value: str) -> str:
    if not _CORP_CODE.fullmatch(value):
        raise ValueError("OpenDART corp_code must be eight digits")
    return value


def _require_report_code(value: str) -> str:
    if value not in _REPORT_CODES:
        raise ValueError("unsupported OpenDART report code")
    return value


def _parse_list[PayloadT](
    body: dict[str, Any],
    item_model: type[PayloadT],
) -> list[PayloadT]:
    raw_items = body.get("list")
    if not isinstance(raw_items, list):
        raise TypeError("OpenDART success response requires list[]")
    if not raw_items:
        raise ValueError("OpenDART success response list must not be empty")
    return [item_model.model_validate(item) for item in raw_items]  # type: ignore[attr-defined]


def _parse_disclosure_page(
    body: dict[str, Any],
    *,
    corp_code: str,
    begin_date: date,
    end_date: date,
    requested_page_no: int,
) -> DartDisclosurePage:
    items = _parse_list(body, DartDisclosureItem)
    page = DartDisclosurePage(
        items=tuple(items),
        page_no=int(body["page_no"]),
        page_count=int(body["page_count"]),
        total_count=int(body["total_count"]),
        total_page=int(body["total_page"]),
    )
    if page.page_no != requested_page_no:
        raise ValueError("OpenDART disclosure page does not match the request")
    if page.total_page < page.page_no or page.total_count < len(page.items):
        raise ValueError("OpenDART disclosure pagination is inconsistent")
    if any(
        item.corp_code != corp_code
        or item.receipt_date < begin_date
        or item.receipt_date > end_date
        for item in page.items
    ):
        raise ValueError("OpenDART disclosure response does not match the request")
    return page


class OpenDartAnalysisProvider:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._limiter = AsyncRateLimiter(settings.dart_requests_per_second)

    @asynccontextmanager
    async def shared_session(self):
        """Reuse one HTTP connection pool for a multi-request refresh."""
        if self._client is not None:
            yield
            return
        async with httpx.AsyncClient(
            timeout=self._settings.http_timeout_seconds,
            follow_redirects=False,
        ) as client:
            self._client = client
            try:
                yield
            finally:
                self._client = None

    @property
    def name(self) -> str:
        return "OpenDART"

    def connection_status(self) -> ConnectionStatusItem:
        configured = bool(
            self._settings.dart_api_key
            and self._settings.dart_api_key.get_secret_value().strip()
        )
        return ConnectionStatusItem(
            provider=self.name,
            state=(
                ConnectionState.NOT_VERIFIED
                if configured
                else ConnectionState.NOT_CONFIGURED
            ),
            detail=(
                "인증키가 설정됐으나 분석 API 실제 호출은 아직 미검증입니다."
                if configured
                else "필요 환경변수: DART_API_KEY"
            ),
            checked_at=now_kst(),
        )

    async def fetch_disclosures(
        self,
        *,
        corp_code: str,
        begin_date: date,
        end_date: date,
        page_no: int = 1,
        publication_type: str | None = "A",
    ) -> ApiResponse[DartDisclosurePage]:
        _require_corp_code(corp_code)
        if begin_date > end_date:
            raise ValueError("begin_date must not be after end_date")
        if page_no < 1:
            raise ValueError("page_no must be positive")
        if publication_type is not None and publication_type not in set(
            "ABCDEFGHIJ"
        ):
            raise ValueError("publication_type must be A-J or None")
        request_parameters = {
            "corp_code": corp_code,
            "bgn_de": begin_date.strftime("%Y%m%d"),
            "end_de": end_date.strftime("%Y%m%d"),
            "last_reprt_at": "N",
            "sort": "date",
            "sort_mth": "desc",
            "page_no": str(page_no),
            "page_count": "100",
        }
        if publication_type is not None:
            request_parameters["pblntf_ty"] = publication_type
        return await self._fetch_json(
            endpoint=DART_DISCLOSURE_ENDPOINT,
            function_name=DART_DISCLOSURE_FUNCTION,
            request_parameters=request_parameters,
            parser=lambda body: _parse_disclosure_page(
                body,
                corp_code=corp_code,
                begin_date=begin_date,
                end_date=end_date,
                requested_page_no=page_no,
            ),
        )

    async def fetch_financials(
        self,
        *,
        corp_code: str,
        business_year: int,
        report_code: str,
        scope: FinancialScope,
    ) -> ApiResponse[list[DartFinancialAccountItem]]:
        _require_corp_code(corp_code)
        _require_report_code(report_code)
        if business_year < 2015:
            raise ValueError("OpenDART financial data starts in 2015")
        if scope not in {
            FinancialScope.CONSOLIDATED,
            FinancialScope.SEPARATE,
        }:
            raise ValueError("financial scope must be CFS or OFS")
        return await self._fetch_json(
            endpoint=DART_FINANCIAL_ENDPOINT,
            function_name=DART_FINANCIAL_FUNCTION,
            request_parameters={
                "corp_code": corp_code,
                "bsns_year": str(business_year),
                "reprt_code": report_code,
                "fs_div": scope.value,
            },
            parser=lambda body: self._parse_financial_records(
                body,
                corp_code=corp_code,
                business_year=business_year,
                report_code=report_code,
            ),
            scope=scope,
        )

    async def fetch_company_profile(
        self,
        *,
        corp_code: str,
    ) -> ApiResponse[DartCompanyProfileItem]:
        _require_corp_code(corp_code)
        return await self._fetch_json(
            endpoint=DART_COMPANY_ENDPOINT,
            function_name=DART_COMPANY_FUNCTION,
            request_parameters={"corp_code": corp_code},
            parser=lambda body: self._parse_company_profile(
                body,
                corp_code=corp_code,
            ),
        )

    async def fetch_dividends(
        self,
        *,
        corp_code: str,
        business_year: int,
        report_code: str = "11011",
    ) -> ApiResponse[list[DartDividendFactItem]]:
        _require_corp_code(corp_code)
        _require_report_code(report_code)
        if business_year < 2015:
            raise ValueError("OpenDART dividend data starts in 2015")
        return await self._fetch_json(
            endpoint=DART_DIVIDEND_ENDPOINT,
            function_name=DART_DIVIDEND_FUNCTION,
            request_parameters={
                "corp_code": corp_code,
                "bsns_year": str(business_year),
                "reprt_code": report_code,
            },
            parser=lambda body: self._parse_dividend_records(
                body,
                corp_code=corp_code,
                business_year=business_year,
            ),
        )

    async def fetch_audit_opinions(
        self,
        *,
        corp_code: str,
        business_year: int,
        report_code: str = "11011",
    ) -> ApiResponse[list[DartAuditOpinionItem]]:
        _require_corp_code(corp_code)
        _require_report_code(report_code)
        if business_year < 2015:
            raise ValueError("OpenDART audit data starts in 2015")
        return await self._fetch_json(
            endpoint=DART_AUDIT_ENDPOINT,
            function_name=DART_AUDIT_FUNCTION,
            request_parameters={
                "corp_code": corp_code,
                "bsns_year": str(business_year),
                "reprt_code": report_code,
            },
            parser=lambda body: self._parse_audit_records(
                body,
                corp_code=corp_code,
                business_year=business_year,
            ),
        )

    async def _fetch_json[PayloadT](
        self,
        *,
        endpoint: str,
        function_name: str,
        request_parameters: dict[str, str],
        parser: Callable[[dict[str, Any]], PayloadT],
        scope: FinancialScope = FinancialScope.NOT_APPLICABLE,
    ) -> ApiResponse[PayloadT]:
        collected_at = now_kst()
        key = (
            self._settings.dart_api_key.get_secret_value().strip()
            if self._settings.dart_api_key
            else ""
        )
        metadata = self._metadata(
            function_name,
            endpoint,
            DataState.NOT_CONFIGURED,
            collected_at,
            scope,
        )
        if not key:
            return ApiResponse(
                state=DataState.NOT_CONFIGURED,
                metadata=metadata,
                error_message="DART_API_KEY is not configured",
            )

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self._settings.http_timeout_seconds,
            follow_redirects=False,
        )
        try:
            response = await request_with_retry(
                client,
                self._limiter,
                "GET",
                endpoint,
                retries=self._settings.http_retries,
                backoff_seconds=self._settings.http_backoff_seconds,
                params={"crtfc_key": key, **request_parameters},
            )
        except httpx.TransportError as exc:
            return ApiResponse(
                state=DataState.FETCH_FAILED,
                metadata=self._metadata(
                    function_name,
                    endpoint,
                    DataState.FETCH_FAILED,
                    collected_at,
                    scope,
                ),
                error_code="NETWORK_ERROR",
                error_message=(f"OpenDART request failed: {type(exc).__name__}"),
            )
        finally:
            if owns_client:
                await client.aclose()

        raw_content = response.content
        base_kwargs: _ResponseDetails = {
            "http_status": response.status_code,
            "response_hash": sha256(raw_content).hexdigest(),
            "content_type": response.headers.get("content-type"),
            "raw_content": raw_content,
        }
        if len(raw_content) > self._settings.max_api_response_bytes:
            return self._failed(
                function_name,
                endpoint,
                collected_at,
                scope,
                "RESPONSE_TOO_LARGE",
                "OpenDART response exceeded configured size limit",
                **base_kwargs,
            )
        if not 200 <= response.status_code <= 299:
            return self._failed(
                function_name,
                endpoint,
                collected_at,
                scope,
                "HTTP_ERROR",
                f"OpenDART returned HTTP {response.status_code}",
                **base_kwargs,
            )
        try:
            body = json.loads(raw_content)
            if not isinstance(body, dict):
                raise TypeError("OpenDART JSON root must be an object")
            status = str(body.get("status", "")).strip()
            message = str(body.get("message", "")).strip()
            if not status:
                raise ValueError("OpenDART response status is missing")
            if status == "013":
                state = DataState.MISSING
                return ApiResponse(
                    state=state,
                    metadata=self._metadata(
                        function_name,
                        endpoint,
                        state,
                        collected_at,
                        scope,
                    ),
                    error_code=status,
                    error_message=message or "OpenDART returned no data",
                    **base_kwargs,
                )
            if status != "000":
                return self._failed(
                    function_name,
                    endpoint,
                    collected_at,
                    scope,
                    status,
                    message or "OpenDART returned an error",
                    **base_kwargs,
                )
            payload = parser(body)
        except (
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
            ValidationError,
        ) as exc:
            return self._failed(
                function_name,
                endpoint,
                collected_at,
                scope,
                "SCHEMA_VALIDATION_FAILED",
                (f"OpenDART response schema validation failed: {type(exc).__name__}"),
                **base_kwargs,
            )

        return ApiResponse(
            state=DataState.AVAILABLE,
            metadata=self._metadata(
                function_name,
                endpoint,
                DataState.AVAILABLE,
                collected_at,
                scope,
            ),
            payload=payload,
            **base_kwargs,
        )

    @staticmethod
    def _parse_financial_records(
        body: dict[str, Any],
        *,
        corp_code: str,
        business_year: int,
        report_code: str,
    ) -> list[DartFinancialAccountItem]:
        records = _parse_list(body, DartFinancialAccountItem)
        if any(
            item.corp_code != corp_code
            or item.business_year != business_year
            or item.report_code != report_code
            for item in records
        ):
            raise ValueError("OpenDART financial response does not match the request")
        return records

    @staticmethod
    def _parse_company_profile(
        body: dict[str, Any],
        *,
        corp_code: str,
    ) -> DartCompanyProfileItem:
        item = DartCompanyProfileItem.model_validate(body)
        if item.corp_code != corp_code:
            raise ValueError("OpenDART company response does not match the request")
        return item

    @staticmethod
    def _parse_dividend_records(
        body: dict[str, Any],
        *,
        corp_code: str,
        business_year: int,
    ) -> list[DartDividendFactItem]:
        records = _parse_list(body, DartDividendFactItem)
        receipt_numbers = {item.receipt_no for item in records}
        if (
            any(
                item.corp_code != corp_code or item.fiscal_date.year != business_year
                for item in records
            )
            or len(receipt_numbers) != 1
        ):
            raise ValueError("OpenDART dividend response does not match the request")
        return records

    @staticmethod
    def _parse_audit_records(
        body: dict[str, Any],
        *,
        corp_code: str,
        business_year: int,
    ) -> list[DartAuditOpinionItem]:
        records = _parse_list(body, DartAuditOpinionItem)
        receipt_numbers = {item.receipt_no for item in records}
        if (
            any(
                item.corp_code != corp_code or item.business_year > business_year
                for item in records
            )
            or not any(item.business_year == business_year for item in records)
            or len(receipt_numbers) != 1
        ):
            raise ValueError("OpenDART audit response does not match the request")
        return records

    def _failed(
        self,
        function_name: str,
        endpoint: str,
        collected_at: datetime,
        scope: FinancialScope,
        error_code: str,
        error_message: str,
        **response_details: Unpack[_ResponseDetails],
    ) -> ApiResponse[Any]:
        return ApiResponse(
            state=DataState.FETCH_FAILED,
            metadata=self._metadata(
                function_name,
                endpoint,
                DataState.FETCH_FAILED,
                collected_at,
                scope,
            ),
            error_code=error_code,
            error_message=error_message,
            **response_details,
        )

    @staticmethod
    def _metadata(
        function_name: str,
        endpoint: str,
        state: DataState,
        collected_at: datetime,
        scope: FinancialScope,
    ) -> DataMetadata:
        return DataMetadata(
            provider="OpenDART",
            function_name=function_name,
            state=state,
            collected_at=collected_at,
            timing=DataTiming.PERIODIC_DISCLOSURE,
            financial_scope=scope,
            source_url=HttpUrl(endpoint),
        )
