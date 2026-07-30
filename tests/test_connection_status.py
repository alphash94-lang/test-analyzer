from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from app.config import Settings
from app.db.models.quality import ApiRawResponse
from app.db.session import create_db_engine, create_session_factory
from app.models.status import ConnectionState
from app.services.connection_status import get_connection_statuses
from app.utils.dates import now_kst
from tests.helpers import make_settings, migrate_database


def as_mapping(settings: Settings) -> dict[str, ConnectionState]:
    return {
        item.provider: item.state for item in get_connection_statuses(settings)
    }


def test_no_keys_show_no_connected_external_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "status.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    statuses = as_mapping(settings)

    assert statuses == {
        "KRX": ConnectionState.NOT_CONFIGURED,
        "OpenDART": ConnectionState.NOT_CONFIGURED,
        "한국투자증권": ConnectionState.NOT_CONFIGURED,
        "KIND": ConnectionState.DEFERRED,
        "네이버 뉴스": ConnectionState.NOT_CONFIGURED,
        "ECOS": ConnectionState.NOT_CONFIGURED,
        "데이터베이스": ConnectionState.CONNECTED,
    }


def test_configured_key_is_still_unverified_without_live_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "configured.db", monkeypatch)
    settings = make_settings(
        database_url=database_url,
        krx_api_key="configured",
        dart_api_key="configured",
        kis_app_key="configured",
        kis_app_secret="configured",
        ncp_apigw_api_key_id="configured",
        ncp_apigw_api_key="configured",
        ecos_api_key="configured",
    )
    statuses = as_mapping(settings)

    for provider in ("KRX", "OpenDART", "한국투자증권", "네이버 뉴스", "ECOS"):
        assert statuses[provider] == ConnectionState.NOT_VERIFIED


def test_database_requires_migration(tmp_path: Path) -> None:
    settings = make_settings(
        database_url=f"sqlite:///{(tmp_path / 'empty.db').as_posix()}",
    )

    assert as_mapping(settings)["데이터베이스"] == ConnectionState.FAILED


def test_latest_failed_attempt_overrides_older_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "attempts.db", monkeypatch)
    settings = make_settings(
        database_url=database_url,
        krx_api_key="configured",
    )
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    received_at = now_kst()
    with sessions.begin() as session:
        session.add_all(
            [
                ApiRawResponse(
                    provider="KRX",
                    function_name="유가증권 종목기본정보",
                    request_params_hash="a" * 64,
                    received_at=received_at,
                    http_status=200,
                    response_hash="b" * 64,
                    normalized_success=True,
                    data_state="AVAILABLE",
                ),
                ApiRawResponse(
                    provider="KRX",
                    function_name="유가증권 종목기본정보",
                    request_params_hash="c" * 64,
                    received_at=received_at + timedelta(seconds=1),
                    http_status=500,
                    response_hash="d" * 64,
                    normalized_success=False,
                    data_state="FETCH_FAILED",
                    error_code="HTTP_ERROR",
                    error_message="HTTP 500",
                ),
            ]
        )

    statuses = as_mapping(settings)

    assert statuses["KRX"] == ConnectionState.FAILED
    engine.dispose()


def test_ecos_successful_attempt_marks_provider_connected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "ecos-status.db", monkeypatch)
    settings = make_settings(
        database_url=database_url,
        ecos_api_key="configured",
    )
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        session.add(
            ApiRawResponse(
                provider="ECOS",
                function_name="통계조회: 한국은행 기준금리",
                request_params_hash="e" * 64,
                received_at=now_kst(),
                http_status=200,
                response_hash="f" * 64,
                normalized_success=True,
                data_state="AVAILABLE",
            )
        )

    assert as_mapping(settings)["ECOS"] == ConnectionState.CONNECTED
    engine.dispose()
