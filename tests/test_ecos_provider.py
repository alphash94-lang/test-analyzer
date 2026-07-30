from __future__ import annotations

import asyncio
from datetime import date

import httpx

from app.models.metadata import DataState
from app.providers.ecos import ECOS_SERIES_BY_KEY, EcosProvider
from tests.helpers import make_settings


def test_ecos_provider_requires_credentials() -> None:
    provider = EcosProvider(make_settings())

    response = asyncio.run(
        provider.fetch_series(
            series=ECOS_SERIES_BY_KEY["base_rate"],
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 29),
        )
    )

    assert response.state == DataState.NOT_CONFIGURED
    assert response.http_status is None


def test_ecos_provider_validates_official_daily_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert "/StatisticSearch/test-key/json/kr/" in request.url.path
        return httpx.Response(
            200,
            json={
                "StatisticSearch": {
                    "list_total_count": 1,
                    "row": [
                        {
                            "STAT_CODE": "722Y001",
                            "STAT_NAME": "1.3.1. 한국은행 기준금리 및 여수신금리",
                            "ITEM_CODE1": "0101000",
                            "ITEM_NAME1": "한국은행 기준금리",
                            "UNIT_NAME": "연%",
                            "TIME": "20260728",
                            "DATA_VALUE": "2.75",
                        }
                    ],
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = EcosProvider(make_settings(ecos_api_key="test-key"), client)
    response = asyncio.run(
        provider.fetch_series(
            series=ECOS_SERIES_BY_KEY["base_rate"],
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 29),
        )
    )
    asyncio.run(client.aclose())

    assert response.state == DataState.AVAILABLE
    assert response.payload is not None
    assert response.payload[0].observed_on == date(2026, 7, 28)
    assert str(response.payload[0].value) == "2.75"


def test_ecos_provider_preserves_api_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "RESULT": {
                    "CODE": "INFO-100",
                    "MESSAGE": "인증키가 유효하지 않습니다.",
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = EcosProvider(make_settings(ecos_api_key="invalid"), client)
    response = asyncio.run(
        provider.fetch_series(
            series=ECOS_SERIES_BY_KEY["base_rate"],
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 29),
        )
    )
    asyncio.run(client.aclose())

    assert response.state == DataState.FETCH_FAILED
    assert response.error_code == "INFO-100"
    assert response.payload is None
