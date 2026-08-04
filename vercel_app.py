from __future__ import annotations

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


app = st.App(
    PROJECT_ROOT / "streamlit_app.py",
    routes=[Route("/api/health", health)],
)
