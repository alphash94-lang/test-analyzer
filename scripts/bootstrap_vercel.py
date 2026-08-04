from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config

from app.config import Settings, get_settings
from app.db.session import create_db_engine, create_session_factory
from app.models.metadata import DataState
from app.providers.base import ApiResponse
from app.providers.dart import (
    DART_CORP_CODE_ENDPOINT,
    DART_CORP_CODE_FUNCTION,
    OpenDartProvider,
)
from app.providers.kind_market_status import (
    KIND_DELISTING_REVIEW_ENDPOINT,
    KIND_DELISTING_REVIEW_FUNCTION,
    KindMarketStatusProvider,
)
from app.providers.kis_reference import (
    KIS_CURRENT_VALUATION_ENDPOINT,
    KIS_CURRENT_VALUATION_FUNCTION,
    KisReferenceProvider,
)
from app.providers.krx import (
    KRX_STOCK_MASTER_ENDPOINT,
    KRX_STOCK_MASTER_FUNCTION,
    KrxProvider,
)
from app.providers.naver_news import (
    NAVER_NEWS_ENDPOINT,
    NAVER_NEWS_FUNCTION,
    NaverNewsProvider,
)
from app.repositories.raw_response_repository import RawResponseRepository
from app.services.phase3_data_service import Phase3DataService
from app.utils.dates import now_kst
from scripts import (
    update_daily_index,
    update_daily_prices,
    update_ecos_macro,
    update_market_screening_data,
    update_phase3_inputs,
    update_phase3_market,
    update_phase4_recommendations,
    update_stock_master,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class BootstrapStep:
    name: str
    run: Callable[[], Awaitable[int]]


def _previous_weekday(value: date) -> date:
    candidate = value - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _save_raw_attempt(
    settings: Settings,
    *,
    provider: str,
    function_name: str,
    endpoint: str,
    request_parameters: dict[str, object],
    response: ApiResponse[Any],
) -> int:
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    try:
        with sessions.begin() as session:
            RawResponseRepository(settings).save(
                session,
                provider=provider,
                function_name=function_name,
                endpoint=endpoint,
                request_parameters=request_parameters,
                response=response,
            )
    finally:
        engine.dispose()
    return 0 if response.state in {DataState.AVAILABLE, DataState.MISSING} else 1


async def _verify_krx(settings: Settings, as_of: date) -> int:
    response = await KrxProvider(settings).fetch(as_of_date=as_of)
    return _save_raw_attempt(
        settings,
        provider="KRX",
        function_name=KRX_STOCK_MASTER_FUNCTION,
        endpoint=KRX_STOCK_MASTER_ENDPOINT,
        request_parameters={"as_of_date": as_of, "market": "KOSPI"},
        response=response,
    )


async def _verify_opendart(settings: Settings) -> int:
    response = await OpenDartProvider(settings).fetch()
    return _save_raw_attempt(
        settings,
        provider="OpenDART",
        function_name=DART_CORP_CODE_FUNCTION,
        endpoint=DART_CORP_CODE_ENDPOINT,
        request_parameters={},
        response=response,
    )


async def _verify_kis(settings: Settings) -> int:
    response = await KisReferenceProvider(settings).fetch_current_valuation(
        symbol="005930"
    )
    return _save_raw_attempt(
        settings,
        provider="한국투자증권",
        function_name=KIS_CURRENT_VALUATION_FUNCTION,
        endpoint=KIS_CURRENT_VALUATION_ENDPOINT,
        request_parameters={"symbol": "005930"},
        response=response,
    )


async def _verify_kind(settings: Settings) -> int:
    response = await KindMarketStatusProvider(settings).fetch_delisting_review(
        symbol="005930"
    )
    return _save_raw_attempt(
        settings,
        provider="KIND",
        function_name=KIND_DELISTING_REVIEW_FUNCTION,
        endpoint=KIND_DELISTING_REVIEW_ENDPOINT,
        request_parameters={"symbol": "005930"},
        response=response,
    )


async def _verify_naver(settings: Settings) -> int:
    response = await NaverNewsProvider(settings).fetch_news(
        query="삼성전자",
        display=1,
    )
    return _save_raw_attempt(
        settings,
        provider="Naver API HUB",
        function_name=NAVER_NEWS_FUNCTION,
        endpoint=NAVER_NEWS_ENDPOINT,
        request_parameters={"query": "삼성전자", "display": 1},
        response=response,
    )


async def _refresh_phase3_window(
    settings: Settings,
    as_of: date,
    *,
    offset_days: int,
) -> int:
    service = Phase3DataService(settings)
    try:
        summary = await service.refresh_window(
            as_of_date=as_of,
            offset_days=offset_days,
            calendar_days=5 if offset_days < 120 else 30,
        )
    finally:
        service.close()
    return 0 if summary.state == DataState.AVAILABLE else 1


async def _run_steps(
    as_of: date,
    *,
    only: str | None = None,
) -> list[dict[str, Any]]:
    settings = get_settings()
    ecos_start = as_of - timedelta(days=30)
    verification_steps = (
        BootstrapStep("krx", lambda: _verify_krx(settings, as_of)),
        BootstrapStep("opendart", lambda: _verify_opendart(settings)),
        BootstrapStep("kis", lambda: _verify_kis(settings)),
        BootstrapStep("kind", lambda: _verify_kind(settings)),
        BootstrapStep("naver", lambda: _verify_naver(settings)),
        BootstrapStep(
            "ecos",
            lambda: update_ecos_macro._run(
                argparse.Namespace(
                    start=ecos_start,
                    end=as_of,
                    series=["base_rate"],
                )
            ),
        ),
    )
    normalized_steps = (
        BootstrapStep("universe", lambda: update_stock_master._run(as_of)),
        BootstrapStep("prices", lambda: update_daily_prices._run(as_of)),
        BootstrapStep("index", lambda: update_daily_index._run(as_of)),
        BootstrapStep("phase3-inputs", lambda: update_phase3_inputs._run(as_of)),
        BootstrapStep(
            "phase3-market",
            lambda: asyncio.to_thread(update_phase3_market._run, as_of),
        ),
        BootstrapStep(
            "screening",
            lambda: update_market_screening_data._run(as_of),
        ),
        BootstrapStep(
            "recommendations",
            lambda: asyncio.to_thread(update_phase4_recommendations._run, as_of),
        ),
    ) + tuple(
        BootstrapStep(
            f"phase3-window-{offset_days}",
            lambda offset_days=offset_days: _refresh_phase3_window(
                settings,
                as_of,
                offset_days=offset_days,
            ),
        )
        for offset_days in (*range(0, 120, 5), *range(120, 390, 30))
    )
    all_steps = verification_steps + normalized_steps
    selected_steps = verification_steps if only is None else tuple(
        step for step in all_steps if step.name == only
    )
    if not selected_steps:
        raise ValueError(f"unknown bootstrap provider: {only}")

    results: list[dict[str, Any]] = []
    for step in selected_steps:
        try:
            returncode = await step.run()
            results.append(
                {
                    "step": step.name,
                    "state": "AVAILABLE" if returncode == 0 else "FAILED",
                    "returncode": returncode,
                }
            )
        except Exception as exc:  # noqa: BLE001 - isolate provider failures
            results.append(
                {
                    "step": step.name,
                    "state": "FAILED",
                    "error_type": type(exc).__name__,
                }
            )
    return results


def bootstrap(*, provider: str | None = None) -> dict[str, Any]:
    """Initialize the schema and run one bounded verification or data step."""

    alembic_config = Config(PROJECT_ROOT / "alembic.ini")
    command.upgrade(alembic_config, "head")

    as_of = _previous_weekday(now_kst().date())
    results = asyncio.run(_run_steps(as_of, only=provider))
    return {
        "status": (
            "ok"
            if all(result["state"] == "AVAILABLE" for result in results)
            else "partial"
        ),
        "as_of": as_of.isoformat(),
        "steps": results,
    }
