from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from datetime import date, datetime
from hashlib import sha256
from typing import Any

import httpx
from pydantic import BaseModel, HttpUrl, ValidationError

from app.config import Settings
from app.models.events import (
    KisAnalystOpinionItem,
    KisInvestorFlowItem,
    KisProgramTradingItem,
    KisShortSellingItem,
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

KIS_BASE_URL = "https://openapi.koreainvestment.com:9443"
KIS_TOKEN_ENDPOINT = f"{KIS_BASE_URL}/oauth2/tokenP"
KIS_OPINION_ENDPOINT = (
    f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/invest-opinion"
)
KIS_FLOW_ENDPOINT = (
    f"{KIS_BASE_URL}"
    "/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily"
)
KIS_PROGRAM_ENDPOINT = (
    f"{KIS_BASE_URL}"
    "/uapi/domestic-stock/v1/quotations/comp-program-trade-daily"
)
KIS_SHORT_ENDPOINT = (
    f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/daily-short-sale"
)
KIS_OPINION_FUNCTION = "국내주식 종목투자의견"
KIS_FLOW_FUNCTION = "종목별 투자자매매동향(일별)"
KIS_PROGRAM_FUNCTION = "프로그램매매 종합현황(일별)"
KIS_SHORT_FUNCTION = "국내주식 공매도 일별추이"

_SYMBOL = re.compile(r"^\d{6}$")


class KisReferenceProvider:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._limiter = AsyncRateLimiter(
            settings.phase5_kis_requests_per_second
        )
        self._access_token: str | None = None

    @property
    def name(self) -> str:
        return "한국투자증권"

    def connection_status(self) -> ConnectionStatusItem:
        configured = self._credentials() is not None
        return ConnectionStatusItem(
            provider=self.name,
            state=(
                ConnectionState.NOT_VERIFIED
                if configured
                else ConnectionState.NOT_CONFIGURED
            ),
            detail=(
                "인증정보가 설정됐으나 Phase 5 참고 데이터 실제 호출은 "
                "아직 검증하지 않았습니다."
                if configured
                else "필요 환경변수: KIS_APP_KEY, KIS_APP_SECRET"
            ),
            checked_at=now_kst(),
        )

    async def fetch_analyst_opinions(
        self,
        *,
        symbol: str,
        begin_date: date,
        end_date: date,
    ) -> ApiResponse[list[KisAnalystOpinionItem]]:
        self._validate_request(symbol, begin_date, end_date)
        return await self._fetch_list(
            endpoint=KIS_OPINION_ENDPOINT,
            function_name=KIS_OPINION_FUNCTION,
            tr_id="FHKST663300C0",
            parameters={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_COND_SCR_DIV_CODE": "16633",
                "FID_INPUT_ISCD": symbol,
                "FID_INPUT_DATE_1": begin_date.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": end_date.strftime("%Y%m%d"),
            },
            output_field="output",
            item_model=KisAnalystOpinionItem,
            response_validator=lambda rows: all(
                begin_date <= row.published_date <= end_date for row in rows
            ),
        )

    async def fetch_investor_flows(
        self,
        *,
        symbol: str,
        as_of_date: date,
    ) -> ApiResponse[list[KisInvestorFlowItem]]:
        self._validate_request(symbol, as_of_date, as_of_date)
        return await self._fetch_list(
            endpoint=KIS_FLOW_ENDPOINT,
            function_name=KIS_FLOW_FUNCTION,
            tr_id="FHPTJ04160001",
            parameters={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
                "FID_INPUT_DATE_1": as_of_date.strftime("%Y%m%d"),
                "FID_ORG_ADJ_PRC": "",
                "FID_ETC_CLS_CODE": "",
            },
            output_field="output2",
            item_model=KisInvestorFlowItem,
            response_validator=lambda rows: all(
                row.trade_date <= as_of_date for row in rows
            ),
        )

    async def fetch_program_trading(
        self,
        *,
        begin_date: date,
        end_date: date,
    ) -> ApiResponse[list[KisProgramTradingItem]]:
        if begin_date > end_date:
            raise ValueError("begin_date must not be after end_date")
        return await self._fetch_list(
            endpoint=KIS_PROGRAM_ENDPOINT,
            function_name=KIS_PROGRAM_FUNCTION,
            tr_id="FHPPG04600001",
            parameters={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_MRKT_CLS_CODE": "K",
                "FID_INPUT_DATE_1": begin_date.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": end_date.strftime("%Y%m%d"),
            },
            output_field="output",
            item_model=KisProgramTradingItem,
            response_validator=lambda rows: all(
                begin_date <= row.trade_date <= end_date for row in rows
            ),
        )

    async def fetch_short_selling(
        self,
        *,
        symbol: str,
        begin_date: date,
        end_date: date,
    ) -> ApiResponse[list[KisShortSellingItem]]:
        self._validate_request(symbol, begin_date, end_date)
        return await self._fetch_list(
            endpoint=KIS_SHORT_ENDPOINT,
            function_name=KIS_SHORT_FUNCTION,
            tr_id="FHPST04830000",
            parameters={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
                "FID_INPUT_DATE_1": begin_date.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": end_date.strftime("%Y%m%d"),
            },
            output_field="output2",
            item_model=KisShortSellingItem,
            response_validator=lambda rows: all(
                begin_date <= row.trade_date <= end_date for row in rows
            ),
        )

    async def _fetch_list[ItemT: BaseModel](
        self,
        *,
        endpoint: str,
        function_name: str,
        tr_id: str,
        parameters: dict[str, str],
        output_field: str,
        item_model: type[ItemT],
        response_validator: Callable[[list[ItemT]], bool],
    ) -> ApiResponse[list[ItemT]]:
        collected_at = now_kst()
        credentials = self._credentials()
        if credentials is None:
            return ApiResponse(
                state=DataState.NOT_CONFIGURED,
                metadata=self._metadata(
                    function_name,
                    endpoint,
                    DataState.NOT_CONFIGURED,
                    collected_at,
                ),
                error_code="MISSING_CREDENTIALS",
                error_message="KIS_APP_KEY and KIS_APP_SECRET are not configured",
            )
        app_key, app_secret = credentials
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self._settings.http_timeout_seconds,
            follow_redirects=False,
        )
        try:
            token, token_error = await self._token(
                client,
                app_key=app_key,
                app_secret=app_secret,
            )
            if token is None:
                return ApiResponse(
                    state=DataState.FETCH_FAILED,
                    metadata=self._metadata(
                        function_name,
                        endpoint,
                        DataState.FETCH_FAILED,
                        collected_at,
                    ),
                    error_code="TOKEN_FAILED",
                    error_message=token_error or "KIS token request failed",
                )
            response = await request_with_retry(
                client,
                self._limiter,
                "GET",
                endpoint,
                retries=self._settings.http_retries,
                backoff_seconds=self._settings.http_backoff_seconds,
                headers={
                    "authorization": f"Bearer {token}",
                    "appkey": app_key,
                    "appsecret": app_secret,
                    "tr_id": tr_id,
                    "custtype": "P",
                },
                params=parameters,
            )
        except httpx.TransportError as exc:
            return ApiResponse(
                state=DataState.FETCH_FAILED,
                metadata=self._metadata(
                    function_name,
                    endpoint,
                    DataState.FETCH_FAILED,
                    collected_at,
                ),
                error_code="NETWORK_ERROR",
                error_message=f"KIS request failed: {type(exc).__name__}",
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
                function_name,
                endpoint,
                collected_at,
                "RESPONSE_TOO_LARGE",
                "KIS response exceeded configured size limit",
                **details,
            )
        if not 200 <= response.status_code <= 299:
            return self._failed(
                function_name,
                endpoint,
                collected_at,
                "HTTP_ERROR",
                f"KIS returned HTTP {response.status_code}",
                **details,
            )
        if response.headers.get("tr_cont", "").strip().upper() in {"M", "F"}:
            return self._failed(
                function_name,
                endpoint,
                collected_at,
                "PARTIAL_RESPONSE_UNSUPPORTED",
                "KIS indicated a continuation page; partial rows were not accepted",
                **details,
            )
        try:
            body = json.loads(raw_content)
            if not isinstance(body, dict):
                raise TypeError("KIS JSON root must be an object")
            return_code = str(body.get("rt_cd", "")).strip()
            if return_code != "0":
                message_code = str(body.get("msg_cd", "")).strip()
                message = str(body.get("msg1", "")).strip()
                return self._failed(
                    function_name,
                    endpoint,
                    collected_at,
                    message_code or return_code or "API_ERROR",
                    message or "KIS returned an error",
                    **details,
                )
            raw_rows = body.get(output_field)
            if isinstance(raw_rows, dict):
                raw_rows = [raw_rows]
            if not isinstance(raw_rows, list):
                raise TypeError(f"KIS success response requires {output_field}[]")
            if not raw_rows:
                return ApiResponse(
                    state=DataState.MISSING,
                    metadata=self._metadata(
                        function_name,
                        endpoint,
                        DataState.MISSING,
                        collected_at,
                    ),
                    error_code="NO_RESULTS",
                    error_message="KIS returned no records",
                    **details,
                )
            rows = [item_model.model_validate(item) for item in raw_rows]
            if not response_validator(rows):
                raise ValueError("KIS response does not match request")
        except (
            json.JSONDecodeError,
            TypeError,
            ValueError,
            ValidationError,
        ) as exc:
            return self._failed(
                function_name,
                endpoint,
                collected_at,
                "SCHEMA_VALIDATION_FAILED",
                f"KIS response schema validation failed: {type(exc).__name__}",
                **details,
            )
        as_of_at = self._as_of_at(rows, collected_at)
        return ApiResponse(
            state=DataState.AVAILABLE,
            metadata=self._metadata(
                function_name,
                endpoint,
                DataState.AVAILABLE,
                collected_at,
                as_of_at=as_of_at,
            ),
            payload=rows,
            **details,
        )

    async def _token(
        self,
        client: httpx.AsyncClient,
        *,
        app_key: str,
        app_secret: str,
    ) -> tuple[str | None, str | None]:
        if self._access_token:
            return self._access_token, None
        try:
            response = await request_with_retry(
                client,
                self._limiter,
                "POST",
                KIS_TOKEN_ENDPOINT,
                retries=self._settings.http_retries,
                backoff_seconds=self._settings.http_backoff_seconds,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "text/plain",
                },
                json={
                    "grant_type": "client_credentials",
                    "appkey": app_key,
                    "appsecret": app_secret,
                },
            )
        except httpx.TransportError as exc:
            return None, f"KIS token request failed: {type(exc).__name__}"
        if not 200 <= response.status_code <= 299:
            return None, f"KIS token endpoint returned HTTP {response.status_code}"
        if len(response.content) > self._settings.max_api_response_bytes:
            return None, "KIS token response exceeded configured size limit"
        try:
            body = json.loads(response.content)
            if not isinstance(body, dict):
                raise TypeError
            token = str(body.get("access_token", "")).strip()
            if not token:
                raise ValueError
        except (json.JSONDecodeError, TypeError, ValueError):
            return None, "KIS token response schema validation failed"
        self._access_token = token
        return token, None

    def _credentials(self) -> tuple[str, str] | None:
        app_key = (
            self._settings.kis_app_key.get_secret_value().strip()
            if self._settings.kis_app_key
            else ""
        )
        app_secret = (
            self._settings.kis_app_secret.get_secret_value().strip()
            if self._settings.kis_app_secret
            else ""
        )
        return (app_key, app_secret) if app_key and app_secret else None

    @staticmethod
    def _validate_request(
        symbol: str,
        begin_date: date,
        end_date: date,
    ) -> None:
        if not _SYMBOL.fullmatch(symbol):
            raise ValueError("KIS symbol must be six digits")
        if begin_date > end_date:
            raise ValueError("begin_date must not be after end_date")

    @staticmethod
    def _as_of_at(rows: Sequence[BaseModel], fallback: datetime) -> datetime:
        row_dates = [
            value
            for row in rows
            for field in ("published_date", "trade_date")
            if isinstance((value := getattr(row, field, None)), date)
        ]
        if not row_dates:
            return fallback
        latest = max(row_dates)
        return datetime.combine(latest, datetime.min.time(), tzinfo=fallback.tzinfo)

    def _failed(
        self,
        function_name: str,
        endpoint: str,
        collected_at: datetime,
        error_code: str,
        error_message: str,
        **details: Any,
    ) -> ApiResponse[Any]:
        return ApiResponse(
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

    def _metadata(
        self,
        function_name: str,
        endpoint: str,
        state: DataState,
        collected_at: datetime,
        *,
        as_of_at: datetime | None = None,
    ) -> DataMetadata:
        return DataMetadata(
            provider=self.name,
            function_name=function_name,
            state=state,
            as_of_at=as_of_at,
            collected_at=collected_at,
            timing=DataTiming.DELAYED,
            financial_scope=FinancialScope.NOT_APPLICABLE,
            is_estimate=function_name == KIS_OPINION_FUNCTION,
            source_url=HttpUrl(endpoint),
        )
