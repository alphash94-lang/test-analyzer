from __future__ import annotations

import asyncio
from unittest.mock import patch

from starlette.requests import Request

from vercel_app import app, bootstrap, health


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


def test_vercel_bootstrap_requires_secret() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/bootstrap",
            "headers": [],
        }
    )

    with patch.dict("os.environ", {}, clear=True):
        response = asyncio.run(bootstrap(request))

    assert response.status_code == 401
    assert response.body == b'{"status":"unauthorized"}'
