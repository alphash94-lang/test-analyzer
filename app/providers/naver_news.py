from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime
from hashlib import sha256
from typing import Any

import httpx
from pydantic import HttpUrl, ValidationError

from app.config import Settings
from app.models.events import NaverNewsPage
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

NAVER_NEWS_ENDPOINT = "https://naverapihub.apigw.ntruss.com/search/v1/news"
NAVER_NEWS_FUNCTION = "네이버 뉴스 검색 API"


class NaverNewsProvider:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._limiter = AsyncRateLimiter(
            settings.phase5_naver_requests_per_second
        )

    @asynccontextmanager
    async def shared_session(self):
        """Reuse one HTTP connection pool for a multi-stock refresh."""
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
        return "Naver API HUB"

    def connection_status(self) -> ConnectionStatusItem:
        configured = bool(self._credentials())
        return ConnectionStatusItem(
            provider="네이버 뉴스",
            state=(
                ConnectionState.NOT_VERIFIED
                if configured
                else ConnectionState.NOT_CONFIGURED
            ),
            detail=(
                "API HUB 인증정보가 설정됐으나 실제 뉴스 호출은 아직 "
                "검증하지 않았습니다."
                if configured
                else "필요 환경변수: NCP_APIGW_API_KEY_ID, NCP_APIGW_API_KEY"
            ),
            checked_at=now_kst(),
        )

    async def fetch_news(
        self,
        *,
        query: str,
        display: int = 50,
        start: int = 1,
        sort: str = "date",
    ) -> ApiResponse[NaverNewsPage]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("Naver news query must not be empty")
        if not 1 <= display <= 100:
            raise ValueError("Naver news display must be between 1 and 100")
        if not 1 <= start <= 1000:
            raise ValueError("Naver news start must be between 1 and 1000")
        if sort not in {"date", "sim"}:
            raise ValueError("Naver news sort must be date or sim")

        collected_at = now_kst()
        credentials = self._credentials()
        if credentials is None:
            return ApiResponse(
                state=DataState.NOT_CONFIGURED,
                metadata=self._metadata(
                    DataState.NOT_CONFIGURED,
                    collected_at,
                ),
                error_code="MISSING_CREDENTIALS",
                error_message=(
                    "NCP_APIGW_API_KEY_ID and NCP_APIGW_API_KEY are not configured"
                ),
            )
        key_id, key = credentials
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
                NAVER_NEWS_ENDPOINT,
                retries=self._settings.http_retries,
                backoff_seconds=self._settings.http_backoff_seconds,
                headers={
                    "X-NCP-APIGW-API-KEY-ID": key_id,
                    "X-NCP-APIGW-API-KEY": key,
                },
                params={
                    "query": normalized_query,
                    "display": str(display),
                    "start": str(start),
                    "sort": sort,
                    "format": "json",
                },
            )
        except httpx.TransportError as exc:
            return ApiResponse(
                state=DataState.FETCH_FAILED,
                metadata=self._metadata(
                    DataState.FETCH_FAILED,
                    collected_at,
                ),
                error_code="NETWORK_ERROR",
                error_message=f"Naver news request failed: {type(exc).__name__}",
            )
        finally:
            if owns_client:
                await client.aclose()

        raw_content = response.content
        details = {
            "http_status": response.status_code,
            "response_hash": sha256(raw_content).hexdigest(),
            "content_type": response.headers.get("content-type"),
            "raw_content": raw_content,
        }
        if len(raw_content) > self._settings.max_api_response_bytes:
            return self._failed(
                collected_at,
                "RESPONSE_TOO_LARGE",
                "Naver news response exceeded configured size limit",
                **details,
            )
        if not 200 <= response.status_code <= 299:
            error_code, error_message = self._read_error(raw_content)
            return self._failed(
                collected_at,
                error_code or "HTTP_ERROR",
                error_message or f"Naver news returned HTTP {response.status_code}",
                **details,
            )
        try:
            body = json.loads(raw_content)
            if not isinstance(body, dict):
                raise TypeError("Naver news JSON root must be an object")
            page = NaverNewsPage.model_validate(body)
            if page.start != start:
                raise ValueError("Naver news response start does not match request")
            if page.display > display:
                raise ValueError("Naver news response display exceeds request")
        except (
            json.JSONDecodeError,
            TypeError,
            ValueError,
            ValidationError,
        ) as exc:
            return self._failed(
                collected_at,
                "SCHEMA_VALIDATION_FAILED",
                f"Naver news schema validation failed: {type(exc).__name__}",
                **details,
            )

        if not page.items:
            return ApiResponse(
                state=DataState.MISSING,
                metadata=self._metadata(DataState.MISSING, collected_at),
                error_code="NO_RESULTS",
                error_message="Naver news returned no articles",
                **details,
            )
        as_of_at = max(item.published_at for item in page.items)
        return ApiResponse(
            state=DataState.AVAILABLE,
            metadata=self._metadata(
                DataState.AVAILABLE,
                collected_at,
                as_of_at=as_of_at,
            ),
            payload=page,
            **details,
        )

    def _credentials(self) -> tuple[str, str] | None:
        key_id = (
            self._settings.ncp_apigw_api_key_id.get_secret_value().strip()
            if self._settings.ncp_apigw_api_key_id
            else ""
        )
        key = (
            self._settings.ncp_apigw_api_key.get_secret_value().strip()
            if self._settings.ncp_apigw_api_key
            else ""
        )
        return (key_id, key) if key_id and key else None

    @staticmethod
    def _read_error(raw_content: bytes) -> tuple[str | None, str | None]:
        try:
            body = json.loads(raw_content)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None, None
        if not isinstance(body, dict):
            return None, None
        code = body.get("errorCode")
        message = body.get("errorMessage")
        normalized_code = str(code).strip() or None if code is not None else None
        normalized_message = (
            str(message).strip() or None if message is not None else None
        )
        return normalized_code, normalized_message

    def _failed(
        self,
        collected_at: datetime,
        error_code: str,
        error_message: str,
        **details: Any,
    ) -> ApiResponse[NaverNewsPage]:
        return ApiResponse(
            state=DataState.FETCH_FAILED,
            metadata=self._metadata(DataState.FETCH_FAILED, collected_at),
            error_code=error_code,
            error_message=error_message,
            **details,
        )

    def _metadata(
        self,
        state: DataState,
        collected_at: datetime,
        *,
        as_of_at: datetime | None = None,
    ) -> DataMetadata:
        return DataMetadata(
            provider=self.name,
            function_name=NAVER_NEWS_FUNCTION,
            state=state,
            as_of_at=as_of_at,
            collected_at=collected_at,
            timing=DataTiming.DELAYED,
            financial_scope=FinancialScope.NOT_APPLICABLE,
            is_estimate=False,
            source_url=HttpUrl(NAVER_NEWS_ENDPOINT),
        )
