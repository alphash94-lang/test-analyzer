from __future__ import annotations

import asyncio
import hmac
import os
from pathlib import Path
from threading import Lock
from time import monotonic

import streamlit as st
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

PROJECT_ROOT = Path(__file__).resolve().parent
_CONNECTION_STATUS_TTL_SECONDS = 30.0
_connection_status_lock = Lock()
_connection_status_cache: tuple[float, list[dict[str, str]]] | None = None


async def health(_: Request) -> JSONResponse:
    """Lightweight endpoint used by Vercel and external uptime checks."""

    return JSONResponse(
        {
            "status": "ok",
            "service": "kospi-analyzer",
            "runtime": "streamlit-asgi",
        }
    )


async def connection_status(_: Request) -> JSONResponse:
    """Expose the same non-secret, stored connection states shown in the UI."""

    providers = await asyncio.to_thread(_cached_connection_status_payload)
    return JSONResponse({"providers": providers})


def _cached_connection_status_payload() -> list[dict[str, str]]:
    """Cache the DB-backed status payload and prevent cold-start stampedes."""

    global _connection_status_cache

    now = monotonic()
    with _connection_status_lock:
        if _connection_status_cache is not None and _connection_status_cache[0] > now:
            return [dict(item) for item in _connection_status_cache[1]]

        from app.config import get_settings
        from app.services.connection_status import get_connection_statuses

        providers = [
            {"provider": item.provider, "state": item.state.value}
            for item in get_connection_statuses(get_settings())
        ]
        _connection_status_cache = (
            monotonic() + _CONNECTION_STATUS_TTL_SECONDS,
            providers,
        )
        return [dict(item) for item in providers]


def _is_authorized(request: Request) -> bool:
    secret = os.environ.get("CRON_SECRET", "")
    supplied = request.headers.get("authorization", "")
    expected = f"Bearer {secret}"
    return bool(secret) and hmac.compare_digest(supplied, expected)


async def bootstrap(request: Request) -> JSONResponse:
    """Run the protected one-time production database/bootstrap workflow."""

    if not _is_authorized(request):
        return JSONResponse({"status": "unauthorized"}, status_code=401)

    from scripts.bootstrap_vercel import bootstrap as run_bootstrap

    provider = request.query_params.get("step") or request.query_params.get("provider")
    try:
        result = await asyncio.to_thread(run_bootstrap, provider=provider)
    except ValueError as exc:
        return JSONResponse({"status": "invalid", "detail": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return JSONResponse(
            {"status": "failed", "error_type": type(exc).__name__},
            status_code=500,
        )
    return JSONResponse(result)


async def scheduled_refresh(request: Request) -> JSONResponse:
    """Run one bounded provider refresh invoked by Vercel Cron."""

    if not _is_authorized(request):
        return JSONResponse({"status": "unauthorized"}, status_code=401)

    from scripts.bootstrap_vercel import (
        SCHEDULED_STEPS,
        scheduled_bootstrap,
    )

    step = str(request.path_params.get("step", ""))
    if step not in SCHEDULED_STEPS:
        return JSONResponse(
            {"status": "invalid", "detail": "unknown scheduled provider"},
            status_code=404,
        )
    try:
        result = await asyncio.to_thread(scheduled_bootstrap, provider=step)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return JSONResponse(
            {"status": "failed", "error_type": type(exc).__name__},
            status_code=500,
        )
    return JSONResponse(
        result,
        status_code=202 if result.get("status") == "busy" else 200,
    )


app = st.App(
    PROJECT_ROOT / "streamlit_app.py",
    routes=[
        Route("/api/health", health),
        Route("/api/connection-status", connection_status),
        Route("/api/bootstrap", bootstrap, methods=["POST"]),
        Route("/api/cron/{step}", scheduled_refresh, methods=["GET"]),
    ],
)
