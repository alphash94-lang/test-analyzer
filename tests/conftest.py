from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.config import get_settings

API_ENVIRONMENT_VARIABLES = (
    "KRX_API_KEY",
    "DART_API_KEY",
    "KIS_APP_KEY",
    "KIS_APP_SECRET",
    "KIS_ACCOUNT_NO",
    "NCP_APIGW_API_KEY_ID",
    "NCP_APIGW_API_KEY",
    "NAVER_CLIENT_ID",
    "NAVER_CLIENT_SECRET",
    "BOK_API_KEY",
    "ECOS_API_KEY",
)


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for variable in API_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

