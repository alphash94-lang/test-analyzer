from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime
from hashlib import sha256
from typing import NotRequired, TypedDict, Unpack

import httpx
from pydantic import HttpUrl

from app.config import Settings
from app.models.kis_master import KisKospiMasterItem
from app.models.metadata import (
    DataMetadata,
    DataState,
    DataTiming,
    FinancialScope,
)
from app.providers.base import ApiResponse
from app.utils.dates import now_kst
from app.utils.http import AsyncRateLimiter, request_with_retry

KIS_KOSPI_MASTER_ENDPOINT = (
    "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip"
)
KIS_KOSPI_MASTER_FUNCTION = "KOSPI 종목마스터"

_SYMBOL = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_FIELD_WIDTHS = (
    2, 1, 4, 4, 4, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 9, 5, 5, 1, 1, 1, 2, 1, 1,
    1, 2, 2, 2, 3, 1, 3, 12, 12, 8, 15, 21, 2, 7, 1, 1, 1, 1, 1,
    9, 9, 9, 5, 9, 8, 9, 3, 1, 1, 1,
)
_TAIL_WIDTH = sum(_FIELD_WIDTHS)


class _ResponseDetails(TypedDict):
    http_status: NotRequired[int]
    response_hash: NotRequired[str]
    content_type: NotRequired[str | None]
    raw_content: NotRequired[bytes]


class KisKospiMasterProvider:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._limiter = AsyncRateLimiter(settings.phase5_kis_requests_per_second)

    async def fetch(self) -> ApiResponse[list[KisKospiMasterItem]]:
        collected_at = now_kst()
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self._settings.http_timeout_seconds,
            follow_redirects=True,
        )
        try:
            response = await request_with_retry(
                client,
                self._limiter,
                "GET",
                KIS_KOSPI_MASTER_ENDPOINT,
                retries=self._settings.http_retries,
                backoff_seconds=self._settings.http_backoff_seconds,
            )
        except httpx.TransportError as exc:
            return self._failed(
                collected_at,
                "NETWORK_ERROR",
                f"KIS master request failed: {type(exc).__name__}",
            )
        finally:
            if owns_client:
                await client.aclose()
        raw = response.content
        details: _ResponseDetails = {
            "http_status": response.status_code,
            "response_hash": sha256(raw).hexdigest(),
            "content_type": response.headers.get("content-type"),
            "raw_content": raw,
        }
        if not 200 <= response.status_code <= 299:
            return self._failed(
                collected_at,
                "HTTP_ERROR",
                f"KIS master returned HTTP {response.status_code}",
                **details,
            )
        try:
            records = self._parse(raw)
        except (OSError, UnicodeError, ValueError, zipfile.BadZipFile) as exc:
            return self._failed(
                collected_at,
                "SCHEMA_VALIDATION_FAILED",
                f"KIS master parse failed: {type(exc).__name__}",
                **details,
            )
        if not records:
            return self._failed(
                collected_at,
                "EMPTY_MASTER",
                "KIS master contained no valid KOSPI records",
                **details,
            )
        return ApiResponse[list[KisKospiMasterItem]](
            state=DataState.AVAILABLE,
            metadata=self._metadata(DataState.AVAILABLE, collected_at),
            payload=records,
            **details,
        )

    @staticmethod
    def _parse(raw: bytes) -> list[KisKospiMasterItem]:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = [
                name
                for name in archive.namelist()
                if name.lower().endswith(".mst")
            ]
            if len(names) != 1:
                raise ValueError("KIS master ZIP must contain one MST file")
            text = archive.read(names[0]).decode("cp949")
        records: list[KisKospiMasterItem] = []
        for line in text.splitlines():
            if len(line) < _TAIL_WIDTH:
                continue
            header = line[:-_TAIL_WIDTH]
            match = _SYMBOL.search(header[:21])
            if match is None:
                continue
            name = header[21:].strip()
            fields: list[str] = []
            cursor = 0
            tail = line[-_TAIL_WIDTH:]
            for width in _FIELD_WIDTHS:
                fields.append(tail[cursor : cursor + width].strip())
                cursor += width
            flag = fields[16].upper()
            records.append(
                KisKospiMasterItem(
                    symbol=match.group(1),
                    name=name,
                    semiconductor_flag=("Y" if flag == "Y" else "N"),
                )
            )
        return records

    def _failed(
        self,
        collected_at: datetime,
        code: str,
        message: str,
        **details: Unpack[_ResponseDetails],
    ) -> ApiResponse[list[KisKospiMasterItem]]:
        return ApiResponse[list[KisKospiMasterItem]](
            state=DataState.FETCH_FAILED,
            metadata=self._metadata(DataState.FETCH_FAILED, collected_at),
            error_code=code,
            error_message=message,
            **details,
        )

    @staticmethod
    def _metadata(
        state: DataState,
        collected_at: datetime,
    ) -> DataMetadata:
        return DataMetadata(
            provider="한국투자증권",
            function_name=KIS_KOSPI_MASTER_FUNCTION,
            state=state,
            as_of_at=collected_at,
            collected_at=collected_at,
            timing=DataTiming.NOT_APPLICABLE,
            financial_scope=FinancialScope.NOT_APPLICABLE,
            is_estimate=False,
            source_url=HttpUrl(KIS_KOSPI_MASTER_ENDPOINT),
        )
