from __future__ import annotations

import asyncio
from time import monotonic
from typing import Any

import httpx


class AsyncRateLimiter:
    def __init__(self, requests_per_second: float) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self._interval = 1.0 / requests_per_second
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            delay = self._interval - (monotonic() - self._last_request)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request = monotonic()


async def request_with_retry(
    client: httpx.AsyncClient,
    limiter: AsyncRateLimiter,
    method: str,
    url: str,
    *,
    retries: int,
    backoff_seconds: float,
    **kwargs: Any,
) -> httpx.Response:
    last_error: httpx.HTTPError | None = None
    for attempt in range(retries + 1):
        await limiter.wait()
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            last_error = exc
        else:
            if response.status_code != 429 and response.status_code < 500:
                return response
            if attempt == retries:
                return response
        if attempt < retries:
            await asyncio.sleep(backoff_seconds * (2**attempt))

    if last_error is None:
        raise RuntimeError("retry loop ended without a response or HTTP error")
    raise last_error
