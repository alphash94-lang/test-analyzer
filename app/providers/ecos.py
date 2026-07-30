from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time
from hashlib import sha256
from typing import Any

import httpx
from pydantic import HttpUrl, TypeAdapter, ValidationError

from app.config import Settings
from app.models.ecos import EcosObservation
from app.models.metadata import DataMetadata, DataState, DataTiming
from app.models.status import ConnectionState, ConnectionStatusItem
from app.providers.base import ApiResponse, BaseProvider
from app.utils.dates import SEOUL, now_kst
from app.utils.http import AsyncRateLimiter, request_with_retry

ECOS_BASE_URL = "https://ecos.bok.or.kr/api"
ECOS_SOURCE_URL = "https://ecos.bok.or.kr/api/#/ServiceUse/ServiceList"
ECOS_STATISTIC_SEARCH_FUNCTION = "통계조회"
ECOS_ENDPOINT_TEMPLATE = (
    f"{ECOS_BASE_URL}/StatisticSearch/{{auth_key}}/json/kr/"
    "{start_row}/{end_row}/{stat_code}/{cycle}/{start_date}/{end_date}/"
    "{item_code}/"
)


@dataclass(frozen=True)
class EcosSeries:
    key: str
    label: str
    stat_code: str
    cycle: str
    item_code: str
    expected_unit: str


ECOS_SERIES: tuple[EcosSeries, ...] = (
    EcosSeries(
        key="base_rate",
        label="한국은행 기준금리",
        stat_code="722Y001",
        cycle="D",
        item_code="0101000",
        expected_unit="연%",
    ),
    EcosSeries(
        key="treasury_3y",
        label="국고채(3년)",
        stat_code="817Y002",
        cycle="D",
        item_code="010200000",
        expected_unit="연%",
    ),
    EcosSeries(
        key="usd_krw_close",
        label="원/달러(종가 15:30)",
        stat_code="731Y003",
        cycle="D",
        item_code="0000003",
        expected_unit="원",
    ),
)
ECOS_SERIES_BY_KEY = {series.key: series for series in ECOS_SERIES}


class EcosProvider(BaseProvider[list[EcosObservation]]):
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._limiter = AsyncRateLimiter(1.0)

    @property
    def name(self) -> str:
        return "ECOS"

    def connection_status(self) -> ConnectionStatusItem:
        configured = bool(self._api_key())
        return ConnectionStatusItem(
            provider=self.name,
            state=(
                ConnectionState.NOT_VERIFIED
                if configured
                else ConnectionState.NOT_CONFIGURED
            ),
            detail=(
                "ECOS 인증키가 설정됐으나 실제 통계조회는 아직 검증되지 않았습니다."
                if configured
                else "필요 환경변수: ECOS_API_KEY 또는 BOK_API_KEY"
            ),
            checked_at=now_kst(),
        )

    async def fetch(
        self,
        **request: object,
    ) -> ApiResponse[list[EcosObservation]]:
        series = request.get("series")
        start_date = request.get("start_date")
        end_date = request.get("end_date")
        if not isinstance(series, EcosSeries):
            raise TypeError("series must be an EcosSeries")
        if not isinstance(start_date, date) or not isinstance(end_date, date):
            raise TypeError("start_date and end_date must be dates")
        return await self.fetch_series(
            series=series,
            start_date=start_date,
            end_date=end_date,
        )

    async def fetch_series(
        self,
        *,
        series: EcosSeries,
        start_date: date,
        end_date: date,
    ) -> ApiResponse[list[EcosObservation]]:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        collected_at = now_kst()
        key = self._api_key()
        if not key:
            return self._unavailable(
                DataState.NOT_CONFIGURED,
                series,
                end_date,
                collected_at,
                "ECOS_API_KEY or BOK_API_KEY is not configured",
            )

        endpoint = ECOS_ENDPOINT_TEMPLATE.format(
            auth_key=key,
            start_row=1,
            end_row=10000,
            stat_code=series.stat_code,
            cycle=series.cycle,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            item_code=series.item_code,
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
            )
        except httpx.TransportError as exc:
            return self._unavailable(
                DataState.FETCH_FAILED,
                series,
                end_date,
                collected_at,
                f"ECOS request failed: {type(exc).__name__}",
                error_code="TRANSPORT_ERROR",
            )
        finally:
            if owns_client:
                await client.aclose()

        raw_content = response.content
        response_hash = sha256(raw_content).hexdigest()
        details = {
            "http_status": response.status_code,
            "response_hash": response_hash,
            "content_type": response.headers.get("content-type"),
            "raw_content": raw_content,
        }
        if len(raw_content) > self._settings.max_api_response_bytes:
            return self._failed(
                series,
                end_date,
                collected_at,
                "RESPONSE_TOO_LARGE",
                "ECOS response exceeded configured size limit",
                **details,
            )
        if not 200 <= response.status_code <= 299:
            return self._failed(
                series,
                end_date,
                collected_at,
                "HTTP_ERROR",
                f"ECOS returned HTTP {response.status_code}",
                **details,
            )

        try:
            body = json.loads(raw_content)
            if not isinstance(body, dict):
                raise TypeError("ECOS JSON root must be an object")
            root = body.get("StatisticSearch")
            if not isinstance(root, dict):
                error = body.get("RESULT")
                if isinstance(error, dict):
                    code = str(error.get("CODE", "")).strip() or "ECOS_ERROR"
                    message = (
                        str(error.get("MESSAGE", "")).strip()
                        or "ECOS returned an error"
                    )
                    return self._failed(
                        series,
                        end_date,
                        collected_at,
                        code,
                        message,
                        **details,
                    )
                raise TypeError("StatisticSearch object is missing")
            rows = root.get("row")
            if not isinstance(rows, list):
                raise TypeError("StatisticSearch.row list is missing")
            records = TypeAdapter(list[EcosObservation]).validate_python(rows)
            for record in records:
                if (
                    record.stat_code != series.stat_code
                    or record.item_code != series.item_code
                    or record.item_name != series.label
                    or record.unit_name != series.expected_unit
                ):
                    raise ValueError("ECOS response does not match requested series")
                if not start_date <= record.observed_on <= end_date:
                    raise ValueError("ECOS observation is outside the request range")
        except (
            json.JSONDecodeError,
            TypeError,
            ValueError,
            ValidationError,
        ) as exc:
            return self._failed(
                series,
                end_date,
                collected_at,
                "SCHEMA_VALIDATION_FAILED",
                f"ECOS response schema validation failed: {type(exc).__name__}",
                **details,
            )

        if not records:
            return ApiResponse(
                state=DataState.MISSING,
                metadata=self._metadata(
                    DataState.MISSING,
                    series,
                    end_date,
                    collected_at,
                ),
                error_code="NO_RESULTS",
                error_message="ECOS returned no observations",
                **details,
            )
        latest_date = max(record.observed_on for record in records)
        return ApiResponse(
            state=DataState.AVAILABLE,
            metadata=self._metadata(
                DataState.AVAILABLE,
                series,
                latest_date,
                collected_at,
            ),
            payload=records,
            **details,
        )

    def _api_key(self) -> str:
        secret = self._settings.ecos_api_key or self._settings.bok_api_key
        return secret.get_secret_value().strip() if secret else ""

    def _metadata(
        self,
        state: DataState,
        series: EcosSeries,
        as_of_date: date,
        collected_at: datetime,
    ) -> DataMetadata:
        return DataMetadata(
            provider=self.name,
            function_name=f"{ECOS_STATISTIC_SEARCH_FUNCTION}: {series.label}",
            state=state,
            as_of_at=datetime.combine(as_of_date, time.min, tzinfo=SEOUL),
            collected_at=collected_at,
            timing=DataTiming.DELAYED,
            source_url=HttpUrl(ECOS_SOURCE_URL),
        )

    def _unavailable(
        self,
        state: DataState,
        series: EcosSeries,
        as_of_date: date,
        collected_at: datetime,
        message: str,
        *,
        error_code: str | None = None,
    ) -> ApiResponse[list[EcosObservation]]:
        return ApiResponse(
            state=state,
            metadata=self._metadata(
                state,
                series,
                as_of_date,
                collected_at,
            ),
            error_code=error_code,
            error_message=message,
        )

    def _failed(
        self,
        series: EcosSeries,
        as_of_date: date,
        collected_at: datetime,
        error_code: str,
        error_message: str,
        **details: Any,
    ) -> ApiResponse[list[EcosObservation]]:
        return ApiResponse[list[EcosObservation]](
            state=DataState.FETCH_FAILED,
            metadata=self._metadata(
                DataState.FETCH_FAILED,
                series,
                as_of_date,
                collected_at,
            ),
            error_code=error_code,
            error_message=error_message,
            **details,
        )
