from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.models.metadata import DataState
from app.providers.krx import KrxProvider
from app.services.universe_service import UniverseService
from app.utils.dates import now_kst
from tests.helpers import make_settings, migrate_database


def test_kosdaq_stock_master_provider_uses_kosdaq_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/sto/ksq_isu_base_info")
        return httpx.Response(
            200,
            request=request,
            json={
                "OutBlock_1": [
                    {
                        "ISU_CD": "KR7098120009",
                        "ISU_SRT_CD": "098120",
                        "ISU_NM": "(주)마이크로컨텍솔루션",
                        "ISU_ABBRV": "마이크로컨텍솔",
                        "ISU_ENG_NM": "Micro Contact Solution",
                        "LIST_DD": "20080923",
                        "MKT_TP_NM": "KOSDAQ",
                        "SECUGRP_NM": "주권",
                        "SECT_TP_NM": "벤처기업부",
                        "KIND_STKCERT_TP_NM": "보통주",
                        "PARVAL": "500",
                        "LIST_SHRS": "8312766",
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = KrxProvider(
        make_settings(krx_api_key="test-key"),
        client,
        market="KOSDAQ",
    )
    response = asyncio.run(provider.fetch(as_of_date=date(2026, 7, 30)))
    asyncio.run(client.aclose())

    assert response.state == DataState.AVAILABLE
    assert response.payload is not None
    assert response.payload[0].symbol == "098120"
    assert response.payload[0].market_type_name == "KOSDAQ"
    assert response.metadata.function_name == "코스닥 종목기본정보"


def test_no_keys_keeps_universe_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "no-keys.db", monkeypatch)
    settings = make_settings(
        database_url=database_url,
        raw_data_dir=tmp_path / "raw",
    )
    service = UniverseService(settings)
    try:
        summary = asyncio.run(service.refresh(now_kst().date()))
        count = service.stock_count()
    finally:
        service.close()

    assert summary.state == DataState.NOT_CONFIGURED.value
    assert summary.stocks_upserted == 0
    assert count == 0
