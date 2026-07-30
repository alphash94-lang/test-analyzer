from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime
from hashlib import sha256
from io import BytesIO
from zipfile import BadZipFile, ZipFile

import httpx
from pydantic import HttpUrl

from app.config import Settings
from app.models.metadata import DataMetadata, DataState, DataTiming
from app.models.status import ConnectionState, ConnectionStatusItem
from app.models.stock import DartCorpCodeItem
from app.providers.base import ApiResponse, BaseProvider
from app.utils.dates import now_kst
from app.utils.http import AsyncRateLimiter, request_with_retry

DART_CORP_CODE_ENDPOINT = "https://opendart.fss.or.kr/api/corpCode.xml"
DART_CORP_CODE_FUNCTION = "고유번호"


class DartApiError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def parse_dart_corp_codes(
    raw_content: bytes,
    *,
    max_xml_bytes: int = 100 * 1024 * 1024,
) -> list[DartCorpCodeItem]:
    try:
        with ZipFile(BytesIO(raw_content)) as archive:
            filenames = [
                name
                for name in archive.namelist()
                if not name.endswith("/") and name.lower().endswith(".xml")
            ]
            if len(filenames) != 1:
                raise ValueError("OpenDART corp-code archive must contain one XML file")
            if archive.getinfo(filenames[0]).file_size > max_xml_bytes:
                raise ValueError(
                    "OpenDART corp-code XML exceeded configured size limit"
                )
            xml_content = archive.read(filenames[0])
    except BadZipFile:
        root = ET.fromstring(raw_content)
        status = (root.findtext("status") or "").strip()
        if status and status != "000":
            raise DartApiError(
                status,
                (root.findtext("message") or "OpenDART returned an error").strip(),
            )
        raise ValueError("OpenDART corp-code success response must be a ZIP")
    if len(xml_content) > max_xml_bytes:
        raise ValueError("OpenDART corp-code XML exceeded configured size limit")

    root = ET.fromstring(xml_content)
    status = (root.findtext("status") or "").strip()
    if status and status != "000":
        raise DartApiError(
            status,
            (root.findtext("message") or "OpenDART returned an error").strip(),
        )

    records: list[DartCorpCodeItem] = []
    for row in root.findall("list"):
        corp_code = _required_xml_text(row, "corp_code")
        corp_name = _required_xml_text(row, "corp_name")
        corp_eng_name = _required_xml_text(
            row,
            "corp_eng_name",
            allow_blank=True,
        )
        stock_code = _required_xml_text(
            row,
            "stock_code",
            allow_blank=True,
        )
        modify_date_raw = _required_xml_text(row, "modify_date")
        if len(modify_date_raw) != 8 or not modify_date_raw.isdigit():
            raise ValueError("OpenDART modify_date must use YYYYMMDD")
        records.append(
            DartCorpCodeItem(
                corp_code=corp_code,
                corp_name=corp_name,
                corp_eng_name=corp_eng_name,
                stock_code=stock_code or None,
                modify_date=date(
                    int(modify_date_raw[:4]),
                    int(modify_date_raw[4:6]),
                    int(modify_date_raw[6:8]),
                ),
            )
        )
    return records


def _required_xml_text(
    row: ET.Element,
    field_name: str,
    *,
    allow_blank: bool = False,
) -> str:
    element = row.find(field_name)
    if element is None:
        raise ValueError(f"OpenDART {field_name} element is missing")
    value = (element.text or "").strip()
    if not allow_blank and not value:
        raise ValueError(f"OpenDART {field_name} must not be empty")
    return value


class OpenDartProvider(BaseProvider[list[DartCorpCodeItem]]):
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._limiter = AsyncRateLimiter(settings.dart_requests_per_second)

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
                "인증키가 설정됐으나 실제 호출 결과는 아직 검증되지 않았습니다."
                if configured
                else "필요 환경변수: DART_API_KEY"
            ),
            checked_at=now_kst(),
        )

    async def fetch(
        self,
        **request: object,
    ) -> ApiResponse[list[DartCorpCodeItem]]:
        del request
        collected_at = now_kst()
        key = (
            self._settings.dart_api_key.get_secret_value().strip()
            if self._settings.dart_api_key
            else ""
        )
        if not key:
            return ApiResponse(
                state=DataState.NOT_CONFIGURED,
                metadata=self._metadata(DataState.NOT_CONFIGURED, collected_at),
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
                DART_CORP_CODE_ENDPOINT,
                retries=self._settings.http_retries,
                backoff_seconds=self._settings.http_backoff_seconds,
                params={"crtfc_key": key},
            )
        except httpx.TransportError as exc:
            return ApiResponse(
                state=DataState.FETCH_FAILED,
                metadata=self._metadata(DataState.FETCH_FAILED, collected_at),
                error_code="NETWORK_ERROR",
                error_message=(f"OpenDART request failed: {type(exc).__name__}"),
            )
        finally:
            if owns_client:
                await client.aclose()

        raw_content = response.content
        response_hash = sha256(raw_content).hexdigest()
        base_kwargs = {
            "http_status": response.status_code,
            "response_hash": response_hash,
            "content_type": response.headers.get("content-type"),
            "raw_content": raw_content,
        }
        if len(raw_content) > self._settings.max_api_response_bytes:
            return ApiResponse(
                state=DataState.FETCH_FAILED,
                metadata=self._metadata(DataState.FETCH_FAILED, collected_at),
                error_code="RESPONSE_TOO_LARGE",
                error_message=("OpenDART response exceeded configured size limit"),
                **base_kwargs,
            )
        if not 200 <= response.status_code <= 299:
            return ApiResponse(
                state=DataState.FETCH_FAILED,
                metadata=self._metadata(DataState.FETCH_FAILED, collected_at),
                error_code="HTTP_ERROR",
                error_message=(f"OpenDART returned HTTP {response.status_code}"),
                **base_kwargs,
            )

        try:
            records = parse_dart_corp_codes(
                raw_content,
                max_xml_bytes=self._settings.max_api_response_bytes,
            )
        except DartApiError as exc:
            return ApiResponse(
                state=DataState.FETCH_FAILED,
                metadata=self._metadata(DataState.FETCH_FAILED, collected_at),
                error_code=exc.code,
                error_message=str(exc),
                **base_kwargs,
            )
        except (ValueError, ET.ParseError) as exc:
            return ApiResponse(
                state=DataState.FETCH_FAILED,
                metadata=self._metadata(DataState.FETCH_FAILED, collected_at),
                error_code="SCHEMA_VALIDATION_FAILED",
                error_message=(
                    f"OpenDART corp-code schema validation failed: {type(exc).__name__}"
                ),
                **base_kwargs,
            )

        if not records:
            return ApiResponse(
                state=DataState.MISSING,
                metadata=self._metadata(DataState.MISSING, collected_at),
                error_message="OpenDART returned an empty corp-code list",
                **base_kwargs,
            )
        return ApiResponse(
            state=DataState.AVAILABLE,
            metadata=self._metadata(DataState.AVAILABLE, collected_at),
            payload=records,
            **base_kwargs,
        )

    def _metadata(
        self,
        state: DataState,
        collected_at: datetime,
    ) -> DataMetadata:
        return DataMetadata(
            provider=self.name,
            function_name=DART_CORP_CODE_FUNCTION,
            state=state,
            collected_at=collected_at,
            timing=DataTiming.NOT_APPLICABLE,
            source_url=HttpUrl(DART_CORP_CODE_ENDPOINT),
        )
