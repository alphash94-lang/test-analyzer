from __future__ import annotations

from datetime import date, datetime, time
from hashlib import sha256

import httpx
from pydantic import HttpUrl, TypeAdapter, ValidationError

from app.config import Settings
from app.models.metadata import DataMetadata, DataState, DataTiming
from app.models.status import ConnectionState, ConnectionStatusItem
from app.models.stock import KrxStockMasterItem
from app.providers.base import ApiResponse, BaseProvider
from app.utils.dates import SEOUL, now_kst
from app.utils.http import AsyncRateLimiter, request_with_retry

KRX_STOCK_MASTER_ENDPOINT = "https://data-dbg.krx.co.kr/svc/apis/sto/stk_isu_base_info"
KRX_STOCK_MASTER_FUNCTION = "유가증권 종목기본정보"


class KrxProvider(BaseProvider[list[KrxStockMasterItem]]):
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._limiter = AsyncRateLimiter(settings.krx_requests_per_second)

    @property
    def name(self) -> str:
        return "KRX"

    def connection_status(self) -> ConnectionStatusItem:
        configured = bool(
            self._settings.krx_api_key
            and self._settings.krx_api_key.get_secret_value().strip()
        )
        return ConnectionStatusItem(
            provider=self.name,
            state=(
                ConnectionState.NOT_VERIFIED
                if configured
                else ConnectionState.NOT_CONFIGURED
            ),
            detail=(
                "인증키가 설정됐으나 실제 호출 결과는 아직 검증되지 않았습니다."
                if configured
                else "필요 환경변수: KRX_API_KEY"
            ),
            checked_at=now_kst(),
        )

    async def fetch(
        self,
        **request: object,
    ) -> ApiResponse[list[KrxStockMasterItem]]:
        requested_date = request.get("as_of_date")
        if not isinstance(requested_date, date):
            raise TypeError("as_of_date must be a date")
        collected_at = now_kst()
        key = (
            self._settings.krx_api_key.get_secret_value().strip()
            if self._settings.krx_api_key
            else ""
        )
        if not key:
            return self._unavailable(
                DataState.NOT_CONFIGURED,
                requested_date,
                collected_at,
                "KRX_API_KEY is not configured",
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
                KRX_STOCK_MASTER_ENDPOINT,
                retries=self._settings.http_retries,
                backoff_seconds=self._settings.http_backoff_seconds,
                headers={"AUTH_KEY": key},
                params={"basDd": requested_date.strftime("%Y%m%d")},
            )
        except httpx.TransportError as exc:
            return self._unavailable(
                DataState.FETCH_FAILED,
                requested_date,
                collected_at,
                f"KRX request failed: {type(exc).__name__}",
            )
        finally:
            if owns_client:
                await client.aclose()

        raw_content = response.content
        response_hash = sha256(raw_content).hexdigest()
        if len(raw_content) > self._settings.max_api_response_bytes:
            return self._failed_response(
                requested_date,
                collected_at,
                response,
                raw_content,
                response_hash,
                "RESPONSE_TOO_LARGE",
                "KRX response exceeded configured size limit",
            )
        if not 200 <= response.status_code <= 299:
            return self._failed_response(
                requested_date,
                collected_at,
                response,
                raw_content,
                response_hash,
                "HTTP_ERROR",
                f"KRX returned HTTP {response.status_code}",
            )

        try:
            body = response.json()
            rows = body.get("OutBlock_1") if isinstance(body, dict) else None
            if not isinstance(rows, list):
                raise TypeError("OutBlock_1 list is missing")
            records = TypeAdapter(list[KrxStockMasterItem]).validate_python(rows)
        except (TypeError, ValueError, ValidationError) as exc:
            return self._failed_response(
                requested_date,
                collected_at,
                response,
                raw_content,
                response_hash,
                "SCHEMA_VALIDATION_FAILED",
                f"KRX response schema validation failed: {type(exc).__name__}",
            )

        if not records:
            return ApiResponse(
                state=DataState.MISSING,
                metadata=self._metadata(
                    DataState.MISSING,
                    requested_date,
                    collected_at,
                ),
                http_status=response.status_code,
                response_hash=response_hash,
                content_type=response.headers.get("content-type"),
                raw_content=raw_content,
                error_message="KRX returned an empty stock-master list",
            )
        return ApiResponse(
            state=DataState.AVAILABLE,
            metadata=self._metadata(
                DataState.AVAILABLE,
                requested_date,
                collected_at,
            ),
            payload=records,
            http_status=response.status_code,
            response_hash=response_hash,
            content_type=response.headers.get("content-type"),
            raw_content=raw_content,
        )

    def _metadata(
        self,
        state: DataState,
        requested_date: date,
        collected_at: datetime,
    ) -> DataMetadata:
        return DataMetadata(
            provider=self.name,
            function_name=KRX_STOCK_MASTER_FUNCTION,
            state=state,
            as_of_at=datetime.combine(requested_date, time.min, tzinfo=SEOUL),
            collected_at=collected_at,
            timing=DataTiming.NOT_APPLICABLE,
            source_url=HttpUrl(KRX_STOCK_MASTER_ENDPOINT),
        )

    def _unavailable(
        self,
        state: DataState,
        requested_date: date,
        collected_at: datetime,
        message: str,
    ) -> ApiResponse[list[KrxStockMasterItem]]:
        return ApiResponse(
            state=state,
            metadata=self._metadata(state, requested_date, collected_at),
            error_message=message,
        )

    def _failed_response(
        self,
        requested_date: date,
        collected_at: datetime,
        response: httpx.Response,
        raw_content: bytes,
        response_hash: str,
        error_code: str,
        error_message: str,
    ) -> ApiResponse[list[KrxStockMasterItem]]:
        return ApiResponse(
            state=DataState.FETCH_FAILED,
            metadata=self._metadata(
                DataState.FETCH_FAILED,
                requested_date,
                collected_at,
            ),
            http_status=response.status_code,
            response_hash=response_hash,
            content_type=response.headers.get("content-type"),
            raw_content=raw_content,
            error_code=error_code,
            error_message=error_message,
        )
