from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.config import Settings, get_settings
from app.db.session import (
    create_db_engine,
    create_session_factory,
    dispose_db_engine,
)
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
from app.services.event_service import EventService
from app.services.event_watchlist_service import EventWatchlistService
from app.services.phase3_data_service import Phase3DataService
from app.utils.dates import now_kst
from scripts import (
    update_daily_index,
    update_daily_prices,
    update_ecos_macro,
    update_market_screening_data,
    update_market_status,
    update_phase3_inputs,
    update_phase3_market,
    update_phase4_recommendations,
    update_stock_master,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENT_SYMBOL = "005930"
WATCHLIST_SHARD_SIZE = 10
WATCHLIST_SHARD_COUNT = 5
KIND_SCHEDULED_STEPS = tuple(
    f"kind-daily-{index}" for index in range(WATCHLIST_SHARD_COUNT)
)
NAVER_SCHEDULED_STEPS = tuple(
    f"naver-daily-{index}" for index in range(WATCHLIST_SHARD_COUNT)
)
SCHEDULED_STEPS = frozenset(
    {
        "krx-daily",
        "ecos-daily",
        "recommendations-daily",
        *KIND_SCHEDULED_STEPS,
        *NAVER_SCHEDULED_STEPS,
    }
)
_local_schedule_locks = {step: Lock() for step in SCHEDULED_STEPS}


@dataclass(frozen=True)
class BootstrapStep:
    name: str
    run: Callable[[], Awaitable[int]]


def _previous_weekday(value: date) -> date:
    candidate = value - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


async def _refresh_recommendations_daily(as_of: date) -> int:
    """Generate the full recommendation run outside the interactive UI request."""

    return await asyncio.to_thread(update_phase4_recommendations._run, as_of)


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
        dispose_db_engine(engine)
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


def _watchlist_symbols(settings: Settings, *, shard_index: int) -> list[str]:
    service = EventWatchlistService(settings)
    try:
        symbols = service.symbols() or [DEFAULT_EVENT_SYMBOL]
    finally:
        service.close()
    start = shard_index * WATCHLIST_SHARD_SIZE
    return symbols[start : start + WATCHLIST_SHARD_SIZE]


async def _refresh_krx_daily(as_of: date) -> int:
    results = (
        await update_stock_master._run(as_of),
        await update_daily_prices._run(as_of),
        await update_daily_index._run(as_of),
    )
    return 0 if all(result == 0 for result in results) else 1


async def _refresh_kind_daily(
    settings: Settings,
    as_of: date,
    *,
    shard_index: int,
) -> int:
    symbols = _watchlist_symbols(settings, shard_index=shard_index)
    return await update_market_status._run(symbols, as_of) if symbols else 0


async def _refresh_naver_daily(
    settings: Settings,
    as_of: date,
    *,
    shard_index: int,
) -> int:
    symbols = _watchlist_symbols(settings, shard_index=shard_index)
    if not symbols:
        return 0
    service = EventService(settings)
    try:
        async with service.shared_session():
            summaries = [
                await service.refresh(
                    symbol=symbol,
                    as_of_date=as_of,
                    events_only=True,
                )
                for symbol in symbols
            ]
    finally:
        service.close()
    successful_states = {DataState.AVAILABLE, DataState.MISSING}
    return (
        0
        if summaries
        and all(summary.state in successful_states for summary in summaries)
        else 1
    )


async def _refresh_ecos_daily(as_of: date) -> int:
    return await update_ecos_macro._run(
        argparse.Namespace(
            start=as_of - timedelta(days=30),
            end=as_of,
            series=None,
        )
    )


async def _run_steps(
    as_of: date,
    *,
    only: str | None = None,
    calendar_date: date | None = None,
) -> list[dict[str, Any]]:
    settings = get_settings()
    daily_date = calendar_date or as_of
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
    scheduled_steps = (
        (
            BootstrapStep("krx-daily", lambda: _refresh_krx_daily(as_of)),
            BootstrapStep("ecos-daily", lambda: _refresh_ecos_daily(daily_date)),
            BootstrapStep(
                "recommendations-daily",
                lambda: _refresh_recommendations_daily(daily_date),
            ),
        )
        + tuple(
            BootstrapStep(
                f"kind-daily-{shard_index}",
                lambda shard_index=shard_index: _refresh_kind_daily(
                    settings,
                    daily_date,
                    shard_index=shard_index,
                ),
            )
            for shard_index in range(WATCHLIST_SHARD_COUNT)
        )
        + tuple(
            BootstrapStep(
                f"naver-daily-{shard_index}",
                lambda shard_index=shard_index: _refresh_naver_daily(
                    settings,
                    daily_date,
                    shard_index=shard_index,
                ),
            )
            for shard_index in range(WATCHLIST_SHARD_COUNT)
        )
    )
    normalized_steps = (
        (
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
        )
        + scheduled_steps
        + tuple(
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
    )
    all_steps = verification_steps + normalized_steps
    selected_steps = (
        verification_steps
        if only is None
        else tuple(step for step in all_steps if step.name == only)
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

    calendar_date = now_kst().date()
    as_of = _previous_weekday(calendar_date)
    results = asyncio.run(
        _run_steps(
            as_of,
            only=provider,
            calendar_date=calendar_date,
        )
    )
    return {
        "status": (
            "ok"
            if all(result["state"] == "AVAILABLE" for result in results)
            else "partial"
        ),
        "as_of": as_of.isoformat(),
        "calendar_date": calendar_date.isoformat(),
        "steps": results,
    }


@contextmanager
def _scheduled_step_lock(settings: Settings, step: str):
    """Prevent duplicate cron deliveries from overlapping the same refresh."""

    engine = create_db_engine(settings)
    connection = None
    local_lock = _local_schedule_locks[step]
    acquired = False
    try:
        if engine.url.get_backend_name() == "postgresql":
            connection = engine.connect()
            lock_id = int.from_bytes(
                sha256(f"kospi-analyzer:{step}".encode()).digest()[:8],
                byteorder="big",
                signed=True,
            )
            acquired = bool(
                connection.scalar(
                    text("SELECT pg_try_advisory_lock(:lock_id)"),
                    {"lock_id": lock_id},
                )
            )
            try:
                yield acquired
            finally:
                if acquired:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_id)"),
                        {"lock_id": lock_id},
                    )
        else:
            acquired = local_lock.acquire(blocking=False)
            yield acquired
    finally:
        if acquired and connection is None:
            local_lock.release()
        if connection is not None:
            connection.close()
        dispose_db_engine(engine)


def scheduled_bootstrap(*, provider: str) -> dict[str, Any]:
    if provider not in SCHEDULED_STEPS:
        raise ValueError(f"unknown scheduled provider: {provider}")
    settings = get_settings()
    with _scheduled_step_lock(settings, provider) as acquired:
        if not acquired:
            return {"status": "busy", "step": provider}
        return bootstrap(provider=provider)
