from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.metadata import DataMetadata, DataState
from app.providers.base import ApiResponse
from app.utils.dates import now_kst


def metadata(state: DataState) -> DataMetadata:
    return DataMetadata(
        provider="test",
        function_name="read-only-test",
        state=state,
        collected_at=now_kst(),
    )


def test_available_response_requires_payload() -> None:
    response = ApiResponse[dict[str, str]](
        state=DataState.AVAILABLE,
        metadata=metadata(DataState.AVAILABLE),
        payload={"status": "verified"},
        http_status=200,
    )

    assert response.payload == {"status": "verified"}


@pytest.mark.parametrize("http_status", [199, 400, 500])
def test_available_response_rejects_non_success_http_status(
    http_status: int,
) -> None:
    with pytest.raises(ValidationError, match="successful HTTP status"):
        ApiResponse[dict[str, str]](
            state=DataState.AVAILABLE,
            metadata=metadata(DataState.AVAILABLE),
            payload={"status": "error-body"},
            http_status=http_status,
        )


def test_error_response_cannot_contain_normal_payload() -> None:
    with pytest.raises(ValidationError, match="must not contain a payload"):
        ApiResponse[dict[str, str]](
            state=DataState.FETCH_FAILED,
            metadata=metadata(DataState.FETCH_FAILED),
            payload={"price": "0"},
            error_message="network unavailable",
        )


def test_response_and_metadata_states_must_match() -> None:
    with pytest.raises(ValidationError, match="must match"):
        ApiResponse[dict[str, str]](
            state=DataState.NOT_VERIFIED,
            metadata=metadata(DataState.AVAILABLE),
        )


def test_fetch_failed_requires_error_detail() -> None:
    with pytest.raises(ValidationError, match="requires an error"):
        ApiResponse[None](
            state=DataState.FETCH_FAILED,
            metadata=metadata(DataState.FETCH_FAILED),
        )
