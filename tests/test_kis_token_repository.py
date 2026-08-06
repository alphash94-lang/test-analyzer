from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, text

from app.models.metadata import DataState
from app.providers.kis_reference import KisReferenceProvider
from app.repositories.kis_token_repository import KisTokenRepository
from app.utils.dates import now_kst
from tests.helpers import make_settings, migrate_database


def test_kis_token_is_encrypted_and_reused_across_provider_instances(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "kis-token.db", monkeypatch)
    settings = make_settings(
        database_url=database_url,
        kis_app_key="durable-key",
        kis_app_secret="durable-secret",
    )
    token_calls = 0
    authorization_headers: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.path == "/oauth2/tokenP":
            token_calls += 1
            return httpx.Response(
                200,
                json={"access_token": "shared-token", "expires_in": 86400},
            )
        authorization_headers.append(request.headers["authorization"])
        return httpx.Response(
            200,
            json={
                "rt_cd": "0",
                "msg_cd": "MCA00000",
                "msg1": "success",
                "output": {"stck_prpr": "4190"},
            },
        )

    async def run_scenario() -> None:
        for _ in range(2):
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ) as client:
                provider = KisReferenceProvider(
                    settings,
                    client,
                    token_repository=KisTokenRepository(settings),
                )
                response = await provider.fetch_current_valuation(symbol="095570")
                assert response.state == DataState.AVAILABLE

    asyncio.run(run_scenario())

    assert token_calls == 1
    assert authorization_headers == [
        "Bearer shared-token",
        "Bearer shared-token",
    ]

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT credential_fingerprint, encrypted_token "
                    "FROM kis_access_tokens"
                )
            ).one()
    finally:
        engine.dispose()
    assert len(row.credential_fingerprint) == 64
    assert "shared-token" not in row.encrypted_token


def test_stale_token_failure_does_not_delete_a_newer_cached_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "kis-token-race.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    repository = KisTokenRepository(settings)

    async def seed() -> None:
        await repository.get_or_refresh(
            app_key="key",
            app_secret="secret",
            refresh=lambda: asyncio.sleep(
                0,
                result=("new-token", now_kst().replace(year=2099), None),
            ),
        )

    asyncio.run(seed())
    repository.invalidate(
        app_key="key",
        app_secret="secret",
        rejected_token="old-token",
    )

    refresh_calls = 0

    async def load() -> tuple[str | None, datetime | None, str | None]:
        nonlocal refresh_calls
        refresh_calls += 1
        return "unexpected-token", now_kst().replace(year=2099), None

    token, _, error = asyncio.run(
        repository.get_or_refresh(
            app_key="key",
            app_secret="secret",
            refresh=load,
        )
    )
    assert token == "new-token"
    assert error is None
    assert refresh_calls == 0
