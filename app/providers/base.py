from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.metadata import DataMetadata, DataState
from app.models.status import ConnectionStatusItem


class ApiResponse[PayloadT](BaseModel):
    """Validated provider result that never converts an error into normal data."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    state: DataState
    metadata: DataMetadata
    payload: PayloadT | None = None
    http_status: int | None = None
    response_hash: str | None = None
    content_type: str | None = None
    raw_content: bytes | None = None
    error_code: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_truthful_state(self) -> ApiResponse[PayloadT]:
        if self.state != self.metadata.state:
            raise ValueError("response state must match metadata state")
        if self.state == DataState.AVAILABLE and self.payload is None:
            raise ValueError("AVAILABLE response requires a payload")
        if self.state == DataState.AVAILABLE and (
            self.http_status is None or not 200 <= self.http_status <= 299
        ):
            raise ValueError("AVAILABLE response requires a successful HTTP status")
        if self.state != DataState.AVAILABLE and self.payload is not None:
            raise ValueError("unavailable response must not contain a payload")
        if (
            self.state == DataState.FETCH_FAILED
            and not self.error_code
            and not self.error_message
        ):
            raise ValueError("FETCH_FAILED response requires an error")
        return self


class BaseProvider[PayloadT](ABC):
    """Read-only provider adapter contract for later collection phases."""

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def connection_status(self) -> ConnectionStatusItem:
        raise NotImplementedError

    @abstractmethod
    async def fetch(self, **request: object) -> ApiResponse[PayloadT]:
        raise NotImplementedError
