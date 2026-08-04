from __future__ import annotations

import asyncio
import hmac
import os
from pathlib import Path

import streamlit as st
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

PROJECT_ROOT = Path(__file__).resolve().parent


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

    from app.config import get_settings
    from app.services.connection_status import get_connection_statuses

    statuses = await asyncio.to_thread(get_connection_statuses, get_settings())
    return JSONResponse(
        {
            "providers": [
                {"provider": item.provider, "state": item.state.value}
                for item in statuses
            ]
        }
    )


async def bootstrap(request: Request) -> JSONResponse:
    """Run the protected one-time production database/bootstrap workflow."""

    secret = os.environ.get("CRON_SECRET", "")
    supplied = request.headers.get("authorization", "")
    expected = f"Bearer {secret}"
    if not secret or not hmac.compare_digest(supplied, expected):
        return JSONResponse({"status": "unauthorized"}, status_code=401)

    from scripts.bootstrap_vercel import bootstrap as run_bootstrap

    provider = request.query_params.get("step") or request.query_params.get(
        "provider"
    )
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


app = st.App(
    PROJECT_ROOT / "streamlit_app.py",
    routes=[
        Route("/api/health", health),
        Route("/api/connection-status", connection_status),
        Route("/api/bootstrap", bootstrap, methods=["POST"]),
    ],
)
