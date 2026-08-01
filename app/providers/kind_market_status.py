from __future__ import annotations

import re
from datetime import datetime
from hashlib import sha256
from typing import NotRequired, TypedDict, Unpack

import httpx
from pydantic import HttpUrl

from app.config import Settings
from app.models.metadata import (
    DataMetadata,
    DataState,
    DataTiming,
    FinancialScope,
)
from app.providers.base import ApiResponse
from app.utils.dates import now_kst
from app.utils.http import AsyncRateLimiter, request_with_retry

KIND_MANAGEMENT_ENDPOINT = (
    "https://kind.krx.co.kr/investwarn/adminissue.do"
)
KIND_TRADING_HALT_ENDPOINT = (
    "https://kind.krx.co.kr/investwarn/tradinghaltissue.do"
)
KIND_DELISTING_REVIEW_ENDPOINT = (
    "https://kind.krx.co.kr/corpgeneral/delistRealInvstg.do"
)

KIND_MANAGEMENT_FUNCTION = "관리종목 조회"
KIND_TRADING_HALT_FUNCTION = "매매거래정지종목 조회"
KIND_DELISTING_REVIEW_FUNCTION = "상장적격성 실질심사 진행법인 조회"

_SYMBOL = re.compile(r"^\d{6}$")
_NO_RESULTS = "조회된 결과값이 없습니다"
_DELISTING_CODE = re.compile(r"detailView\('(?P<code>[0-9A-Z]{5})'")
_TAG = re.compile(r"<[^>]+>")


class _ResponseDetails(TypedDict):
    http_status: NotRequired[int]
    response_hash: NotRequired[str]
    content_type: NotRequired[str | None]
    raw_content: NotRequired[bytes]


class KindMarketStatusProvider:
    """Read KIND's official public KOSPI market-status lists."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._limiter = AsyncRateLimiter(settings.krx_requests_per_second)

    async def fetch_management_issue(
        self,
        *,
        symbol: str,
        stock_names: tuple[str, ...],
    ) -> ApiResponse[bool]:
        return await self._fetch_symbol_status(
            endpoint=KIND_MANAGEMENT_ENDPOINT,
            function_name=KIND_MANAGEMENT_FUNCTION,
            symbol=symbol,
            stock_names=stock_names,
            form={
                "method": "searchAdminIssueSub",
                "forward": "adminissue_sub",
                "currentPageSize": "100",
                "pageIndex": "1",
                "marketType": "1",
                "repIsuSrtCd": symbol,
                "searchCorpName": "",
            },
        )

    async def fetch_trading_halt(
        self,
        *,
        symbol: str,
        stock_names: tuple[str, ...],
    ) -> ApiResponse[bool]:
        return await self._fetch_symbol_status(
            endpoint=KIND_TRADING_HALT_ENDPOINT,
            function_name=KIND_TRADING_HALT_FUNCTION,
            symbol=symbol,
            stock_names=stock_names,
            form={
                "method": "searchTradingHaltIssueSub",
                "forward": "tradinghaltissue_sub",
                "currentPageSize": "100",
                "pageIndex": "1",
                "marketType": "1",
                "repIsuSrtCd": symbol,
                "searchCorpName": "",
                "searchMode": "1",
            },
        )

    async def fetch_delisting_review(
        self,
        *,
        symbol: str,
    ) -> ApiResponse[bool]:
        self._validate_symbol(symbol)
        form = {
            "method": "searchDelistRealInvstg",
            "forward": "delistRealInvstg_sub",
            "currentPageSize": "3000",
            "pageIndex": "1",
            "marketType": "1",
            "ProgDelistType": "1",
            "fromDate": "",
            "toDate": "",
            "orderMode": "2",
            "orderStat": "D",
        }
        response, collected_at = await self._post(
            KIND_DELISTING_REVIEW_ENDPOINT,
            form,
        )
        if isinstance(response, ApiResponse):
            return response
        details, text = self._response_details(response)
        if not 200 <= response.status_code <= 299:
            return self._failed(
                KIND_DELISTING_REVIEW_FUNCTION,
                KIND_DELISTING_REVIEW_ENDPOINT,
                collected_at,
                "HTTP_ERROR",
                f"KIND returned HTTP {response.status_code}",
                **details,
            )
        codes = set(_DELISTING_CODE.findall(text))
        if "<tbody" not in text or not codes and _NO_RESULTS not in text:
            return self._failed(
                KIND_DELISTING_REVIEW_FUNCTION,
                KIND_DELISTING_REVIEW_ENDPOINT,
                collected_at,
                "SCHEMA_VALIDATION_FAILED",
                "KIND delisting-review response structure was not recognized",
                **details,
            )
        return self._available(
            KIND_DELISTING_REVIEW_FUNCTION,
            KIND_DELISTING_REVIEW_ENDPOINT,
            collected_at,
            symbol[:5] in codes,
            **details,
        )

    async def _fetch_symbol_status(
        self,
        *,
        endpoint: str,
        function_name: str,
        symbol: str,
        stock_names: tuple[str, ...],
        form: dict[str, str],
    ) -> ApiResponse[bool]:
        self._validate_symbol(symbol)
        names = tuple(name.strip() for name in stock_names if name.strip())
        if not names:
            raise ValueError("at least one official stock name is required")
        response, collected_at = await self._post(endpoint, form)
        if isinstance(response, ApiResponse):
            return response
        details, text = self._response_details(response)
        if not 200 <= response.status_code <= 299:
            return self._failed(
                function_name,
                endpoint,
                collected_at,
                "HTTP_ERROR",
                f"KIND returned HTTP {response.status_code}",
                **details,
            )
        if _NO_RESULTS in text:
            return self._available(
                function_name,
                endpoint,
                collected_at,
                False,
                **details,
            )
        visible_text = re.sub(r"\s+", "", _TAG.sub(" ", text))
        if "<tbody" not in text or not any(
            re.sub(r"\s+", "", name) in visible_text for name in names
        ):
            return self._failed(
                function_name,
                endpoint,
                collected_at,
                "SCHEMA_VALIDATION_FAILED",
                "KIND response did not contain the requested stock",
                **details,
            )
        return self._available(
            function_name,
            endpoint,
            collected_at,
            True,
            **details,
        )

    async def _post(
        self,
        endpoint: str,
        form: dict[str, str],
    ) -> tuple[httpx.Response | ApiResponse[bool], datetime]:
        collected_at = now_kst()
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self._settings.http_timeout_seconds,
            follow_redirects=False,
        )
        try:
            response = await request_with_retry(
                client,
                self._limiter,
                "POST",
                endpoint,
                retries=self._settings.http_retries,
                backoff_seconds=self._settings.http_backoff_seconds,
                data=form,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            return response, collected_at
        except httpx.TransportError as exc:
            return (
                self._failed(
                    "KIND 공개 시장상태 조회",
                    endpoint,
                    collected_at,
                    "NETWORK_ERROR",
                    f"KIND request failed: {type(exc).__name__}",
                ),
                collected_at,
            )
        finally:
            if owns_client:
                await client.aclose()

    @staticmethod
    def _response_details(
        response: httpx.Response,
    ) -> tuple[_ResponseDetails, str]:
        raw = response.content
        encoding = response.encoding or "utf-8"
        try:
            text = raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("cp949", errors="replace")
        return (
            {
                "http_status": response.status_code,
                "response_hash": sha256(raw).hexdigest(),
                "content_type": response.headers.get("content-type"),
                "raw_content": raw,
            },
            text,
        )

    @staticmethod
    def _validate_symbol(symbol: str) -> None:
        if not _SYMBOL.fullmatch(symbol):
            raise ValueError("KIND symbol must be six digits")

    @staticmethod
    def _metadata(
        function_name: str,
        endpoint: str,
        state: DataState,
        collected_at: datetime,
    ) -> DataMetadata:
        return DataMetadata(
            provider="KIND",
            function_name=function_name,
            state=state,
            as_of_at=collected_at,
            collected_at=collected_at,
            timing=DataTiming.DELAYED,
            financial_scope=FinancialScope.NOT_APPLICABLE,
            is_estimate=False,
            source_url=HttpUrl(endpoint),
        )

    def _available(
        self,
        function_name: str,
        endpoint: str,
        collected_at: datetime,
        value: bool,
        **details: Unpack[_ResponseDetails],
    ) -> ApiResponse[bool]:
        return ApiResponse[bool](
            state=DataState.AVAILABLE,
            metadata=self._metadata(
                function_name,
                endpoint,
                DataState.AVAILABLE,
                collected_at,
            ),
            payload=value,
            **details,
        )

    def _failed(
        self,
        function_name: str,
        endpoint: str,
        collected_at: datetime,
        error_code: str,
        error_message: str,
        **details: Unpack[_ResponseDetails],
    ) -> ApiResponse[bool]:
        return ApiResponse[bool](
            state=DataState.FETCH_FAILED,
            metadata=self._metadata(
                function_name,
                endpoint,
                DataState.FETCH_FAILED,
                collected_at,
            ),
            error_code=error_code,
            error_message=error_message,
            **details,
        )
