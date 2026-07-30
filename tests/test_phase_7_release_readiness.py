from __future__ import annotations

import asyncio
import importlib
import logging
import re
import sys
import tomllib
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from streamlit.testing.v1 import AppTest

import app.db.models  # noqa: F401
from app.config import get_settings
from app.db.base import Base
from app.db.models.quality import ApiRawResponse
from app.db.session import create_db_engine, create_session_factory
from app.logging_config import SensitiveValueFilter
from app.models.metadata import DataMetadata, DataState
from app.models.status import ConnectionState
from app.providers.base import ApiResponse
from app.providers.kis_reference import KIS_TOKEN_ENDPOINT
from app.repositories.raw_response_repository import RawResponseRepository
from app.repositories.stock_repository import StockRepository
from app.services.connection_status import get_connection_statuses
from app.services.stock_classification import classify_krx_stock
from app.utils.dates import now_kst
from app.utils.http import AsyncRateLimiter, request_with_retry
from tests.helpers import make_settings, migrate_database
from tests.test_stock_classification import minimum_item

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "message",
    [
        "GET https://opendart.fss.or.kr/api/list.json?crtfc_key=super-secret",
        "appkey=super-secret",
        "appsecret: super-secret",
        "Authorization: Bearer super-secret",
        "postgresql+psycopg://user:super-secret@db.example/app",
        "X-NCP-APIGW-API-KEY=super-secret",
    ],
)
def test_logging_filter_redacts_real_credential_shapes(message: str) -> None:
    record = logging.LogRecord(
        name="phase7",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )

    assert SensitiveValueFilter().filter(record) is True
    assert "super-secret" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()


@pytest.mark.parametrize(
    ("module_name", "arguments"),
    [
        (
            "scripts.update_stock_analysis",
            ["--symbol", "000001", "--as-of", "2026-07-30"],
        ),
        (
            "scripts.update_phase5_events",
            ["--symbol", "000001", "--as-of", "2026-07-30"],
        ),
    ],
)
def test_cli_exception_output_redacts_configured_secret(
    module_name: str,
    arguments: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "provider-echoed-credential"
    module = importlib.import_module(module_name)

    async def fail(_args: object) -> int:
        raise ValueError(f"upstream echoed {secret}")

    monkeypatch.setattr(module, "_run", fail)
    monkeypatch.setattr(sys, "argv", [module_name, *arguments])
    monkeypatch.setenv("DART_API_KEY", secret)
    get_settings.cache_clear()

    assert module.main() == 1
    output = capsys.readouterr().out
    assert secret not in output
    assert "[REDACTED]" in output


def test_runtime_provider_endpoints_are_in_api_contract() -> None:
    contract = (PROJECT_ROOT / "docs/api_contract.md").read_text(
        encoding="utf-8"
    )

    assert KIS_TOKEN_ENDPOINT in contract
    assert "`access_token`" in contract


def test_partial_provider_configuration_marks_old_success_as_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "partial.db", monkeypatch)
    settings = make_settings(
        database_url=database_url,
        krx_api_key="configured",
        data_freshness_warning_hours=48,
    )
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        session.add(
            ApiRawResponse(
                provider="KRX",
                function_name="유가증권 종목기본정보",
                request_params_hash="a" * 64,
                received_at=now_kst() - timedelta(hours=49),
                http_status=200,
                response_hash="b" * 64,
                normalized_success=True,
                data_state="AVAILABLE",
            )
        )

    statuses = {item.provider: item for item in get_connection_statuses(settings)}

    assert statuses["KRX"].state.value == "데이터 지연"
    assert "48시간" in statuses["KRX"].detail
    assert statuses["OpenDART"].state == ConnectionState.NOT_CONFIGURED
    engine.dispose()


def test_stale_provider_warning_is_visible_in_streamlit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "stale-ui.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        session.add(
            ApiRawResponse(
                provider="KRX",
                function_name="유가증권 종목기본정보",
                request_params_hash="d" * 64,
                received_at=now_kst() - timedelta(hours=49),
                http_status=200,
                response_hash="e" * 64,
                normalized_success=True,
                data_state="AVAILABLE",
            )
        )
    engine.dispose()
    monkeypatch.setenv("KRX_API_KEY", "configured")
    monkeypatch.setenv("DATA_FRESHNESS_WARNING_HOURS", "48")
    get_settings.cache_clear()

    app = AppTest.from_file("app/main.py", default_timeout=20).run()
    rendered = "\n".join(
        str(element.value)
        for collection in (
            app.markdown,
            app.caption,
            app.warning,
            app.error,
            app.info,
        )
        for element in collection
    )

    assert not app.exception
    assert "데이터 지연" in rendered
    assert "48시간" in rendered


def test_http_timeout_is_retried_and_never_becomes_a_response() -> None:
    attempts = 0

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("provider timeout", request=request)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(timeout_handler)
        ) as client:
            with pytest.raises(httpx.ReadTimeout):
                await request_with_retry(
                    client,
                    AsyncRateLimiter(1000),
                    "GET",
                    "https://provider.invalid/read-only",
                    retries=1,
                    backoff_seconds=0,
                )

    asyncio.run(run())
    assert attempts == 2


def test_stock_search_treats_sql_injection_text_as_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "search.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    repository = StockRepository()
    collected_at = now_kst()
    with sessions.begin() as session:
        repository.upsert_krx_records(
            session,
            [classify_krx_stock(minimum_item(name="정상기업"))],
            as_of_at=collected_at,
            collected_at=collected_at,
        )

    with sessions() as session:
        assert repository.search(session, "' OR 1=1 --") == []
        assert repository.search(session, "%") == []
        assert repository.search(session, "_") == []
    engine.dispose()


def test_required_release_artifacts_and_operations_guides_exist() -> None:
    required_paths = (
        "pyproject.toml",
        ".env.example",
        "README.md",
        "docs/api_contract.md",
        "docs/data_dictionary.md",
        "docs/scoring_rules.md",
        "docs/investment_logic.md",
        "docs/FINAL_COMPLETION_CHECKLIST.md",
        "tests/fixtures/REAL_RESPONSE_STATUS.md",
    )
    for relative_path in required_paths:
        path = PROJECT_ROOT / relative_path
        assert path.is_file(), relative_path
        assert path.stat().st_size > 0, relative_path

    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    for heading in (
        "## 초보자 빠른 시작",
        "## 초기수집",
        "## 증분갱신",
        "## 백업과 복구",
        "## 문제 해결",
        "## 배포 전 검증",
    ):
        assert heading in readme


def test_dev_install_includes_every_documented_verification_tool() -> None:
    pyproject = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    dependencies = pyproject["project"]["optional-dependencies"]["dev"]

    for package in ("pytest", "ruff", "pyright"):
        assert any(
            requirement.lower().startswith(package)
            for requirement in dependencies
        ), package


def test_data_dictionary_covers_every_domain_table() -> None:
    dictionary = (PROJECT_ROOT / "docs/data_dictionary.md").read_text(
        encoding="utf-8"
    )
    undocumented = [
        table_name
        for table_name in sorted(Base.metadata.tables)
        if f"`{table_name}`" not in dictionary
    ]
    assert undocumented == []


def test_raw_response_repository_deduplicates_same_request_and_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "raw-dedup.db", monkeypatch)
    settings = make_settings(
        database_url=database_url,
        raw_data_dir=tmp_path / "raw",
    )
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    repository = RawResponseRepository(settings)
    response = ApiResponse[dict[str, bool]](
        state=DataState.AVAILABLE,
        metadata=DataMetadata(
            provider="TEST",
            function_name="READ_ONLY",
            state=DataState.AVAILABLE,
            collected_at=now_kst(),
        ),
        payload={"ok": True},
        http_status=200,
        raw_content=b'{"ok":true}',
        response_hash="c" * 64,
        content_type="application/json",
    )

    with sessions.begin() as session:
        first = repository.save(
            session,
            provider="TEST",
            function_name="READ_ONLY",
            endpoint="https://provider.invalid/read-only",
            request_parameters={"date": "2026-07-30"},
            response=response,
        )
        second = repository.save(
            session,
            provider="TEST",
            function_name="READ_ONLY",
            endpoint="https://provider.invalid/read-only",
            request_parameters={"date": "2026-07-30"},
            response=response,
        )
        assert first is not None
        assert second is not None
        assert first is second

    with sessions() as session:
        assert session.scalar(
            select(func.count()).select_from(ApiRawResponse)
        ) == 1
    assert len(list((tmp_path / "raw").rglob("*.json"))) == 1
    engine.dispose()


def test_final_checklist_has_all_twenty_criteria_and_allowed_states() -> None:
    checklist = (
        PROJECT_ROOT / "docs/FINAL_COMPLETION_CHECKLIST.md"
    ).read_text(encoding="utf-8")
    rows = re.findall(
        r"^\|\s*(\d{1,2})\s*\|.*?\|\s*"
        r"(충족|부분 충족|미충족|API 키 또는 외부 데이터 필요|"
        r"현재 API 제공 범위에서 구현 곤란)\s*\|",
        checklist,
        flags=re.MULTILINE,
    )

    assert [int(number) for number, _state in rows] == list(range(1, 21))


def test_env_files_do_not_ship_credentials_and_are_ignored() -> None:
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in gitignore
    assert ".env.*" in gitignore
    assert "!.env.example" in gitignore

    env_values = {}
    for raw_line in (
        PROJECT_ROOT / ".env.example"
    ).read_text(encoding="utf-8").splitlines():
        if "=" not in raw_line or raw_line.lstrip().startswith("#"):
            continue
        name, value = raw_line.split("=", 1)
        env_values[name] = value
    for name in (
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
    ):
        assert env_values[name] == ""


def test_unavailable_real_fixtures_are_recorded_not_fabricated() -> None:
    fixture_dir = PROJECT_ROOT / "tests" / "fixtures"
    status = (fixture_dir / "REAL_RESPONSE_STATUS.md").read_text(encoding="utf-8")

    assert "미확보" in status
    assert not list(fixture_dir.glob("*.json"))
    assert not list(fixture_dir.glob("*.xml"))
    assert not list(fixture_dir.glob("*.zip"))
