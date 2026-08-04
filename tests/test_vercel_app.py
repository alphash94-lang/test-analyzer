from __future__ import annotations

import asyncio

from starlette.requests import Request

from vercel_app import app, health


def test_vercel_entrypoint_is_asgi_callable() -> None:
    assert callable(app)


def test_vercel_health_endpoint() -> None:
    request = Request({"type": "http", "method": "GET", "path": "/api/health"})

    response = asyncio.run(health(request))

    assert response.status_code == 200
    assert response.body == (
        b'{"status":"ok","service":"kospi-analyzer",'
        b'"runtime":"streamlit-asgi"}'
    )
