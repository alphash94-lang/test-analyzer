from __future__ import annotations

import json
import re
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models.quality import ApiRawResponse
from app.models.metadata import DataState
from app.providers.base import ApiResponse

_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9_.-]+")


class RawResponseRepository:
    def __init__(self, settings: Settings) -> None:
        self._raw_data_dir = settings.raw_data_dir

    def save(
        self,
        session: Session,
        *,
        provider: str,
        function_name: str,
        endpoint: str,
        request_parameters: dict[str, object],
        response: ApiResponse[Any],
    ) -> ApiRawResponse | None:
        if response.raw_content is None or response.http_status is None:
            return None

        request_json = json.dumps(
            request_parameters,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        request_hash = sha256(request_json.encode("utf-8")).hexdigest()
        response_hash = (
            response.response_hash or sha256(response.raw_content).hexdigest()
        )
        existing = session.scalar(
            select(ApiRawResponse).where(
                ApiRawResponse.provider == provider,
                ApiRawResponse.function_name == function_name,
                ApiRawResponse.request_params_hash == request_hash,
                ApiRawResponse.response_hash == response_hash,
            )
        )
        if existing is not None:
            existing.received_at = response.metadata.collected_at
            existing.as_of_at = response.metadata.as_of_at
            existing.http_status = response.http_status
            existing.content_type = response.content_type
            existing.normalized_success = response.state == DataState.AVAILABLE
            existing.data_state = response.state.value
            existing.error_code = response.error_code
            existing.error_message = response.error_message
            return existing
        storage_path = self._write_raw(
            provider=provider,
            received_at=response.metadata.collected_at,
            response_hash=response_hash,
            content_type=response.content_type,
            raw_content=response.raw_content,
        )
        response_body = self._decode_text(
            response.raw_content,
            response.content_type,
        )
        row = ApiRawResponse(
            provider=provider,
            function_name=function_name,
            endpoint=endpoint,
            request_params_hash=request_hash,
            received_at=response.metadata.collected_at,
            as_of_at=response.metadata.as_of_at,
            http_status=response.http_status,
            response_body=response_body,
            raw_storage_path=storage_path.as_posix(),
            content_type=response.content_type,
            response_hash=response_hash,
            normalized_success=response.state == DataState.AVAILABLE,
            data_state=response.state.value,
            error_code=response.error_code,
            error_message=response.error_message,
        )
        session.add(row)
        session.flush()
        return row

    @staticmethod
    def set_normalization_result(
        session: Session,
        raw_response_id: int | None,
        *,
        success: bool,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if raw_response_id is None:
            return
        row = session.get(ApiRawResponse, raw_response_id)
        if row is None:
            return
        row.normalized_success = success
        if success:
            if row.data_state == DataState.AVAILABLE.value:
                row.error_code = None
                row.error_message = None
            return
        row.error_code = error_code or row.error_code
        row.error_message = error_message or row.error_message

    def _write_raw(
        self,
        *,
        provider: str,
        received_at: datetime,
        response_hash: str,
        content_type: str | None,
        raw_content: bytes,
    ) -> Path:
        safe_provider = _SAFE_SEGMENT.sub("_", provider).strip("._") or "unknown"
        suffix = self._suffix(content_type, raw_content)
        path = (
            self._raw_data_dir
            / safe_provider
            / received_at.strftime("%Y/%m/%d")
            / f"{response_hash}.{suffix}"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(raw_content)
        return path

    @staticmethod
    def _suffix(content_type: str | None, raw_content: bytes) -> str:
        normalized = (content_type or "").lower()
        if "json" in normalized:
            return "json"
        if "zip" in normalized or raw_content.startswith(b"PK"):
            return "zip"
        if "xml" in normalized or raw_content.lstrip().startswith(b"<"):
            return "xml"
        return "bin"

    @staticmethod
    def _decode_text(
        raw_content: bytes,
        content_type: str | None,
    ) -> str | None:
        if len(raw_content) > 2 * 1024 * 1024:
            return None
        normalized = (content_type or "").lower()
        if (
            "json" not in normalized
            and "xml" not in normalized
            and not raw_content.lstrip().startswith((b"{", b"[", b"<"))
        ):
            return None
        try:
            return raw_content.decode("utf-8")
        except UnicodeDecodeError:
            return None
