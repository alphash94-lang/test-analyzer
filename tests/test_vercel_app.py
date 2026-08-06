from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request

from vercel_app import app, bootstrap, health, scheduled_refresh


def test_vercel_entrypoint_is_asgi_callable() -> None:
    assert callable(app)


def test_vercel_provider_crons_are_daily_and_bounded() -> None:
    config = json.loads(Path("vercel.json").read_text(encoding="utf-8"))

    assert config["crons"] == [
        {"path": "/api/cron/krx-daily", "schedule": "30 22 * * *"},
        {"path": "/api/cron/kind-daily-0", "schedule": "40 9 * * *"},
        {"path": "/api/cron/kind-daily-1", "schedule": "40 10 * * *"},
        {"path": "/api/cron/kind-daily-2", "schedule": "40 11 * * *"},
        {"path": "/api/cron/kind-daily-3", "schedule": "40 12 * * *"},
        {"path": "/api/cron/kind-daily-4", "schedule": "40 13 * * *"},
        {"path": "/api/cron/naver-daily-0", "schedule": "50 14 * * *"},
        {"path": "/api/cron/naver-daily-1", "schedule": "50 15 * * *"},
        {"path": "/api/cron/naver-daily-2", "schedule": "50 16 * * *"},
        {"path": "/api/cron/naver-daily-3", "schedule": "50 17 * * *"},
        {"path": "/api/cron/naver-daily-4", "schedule": "50 18 * * *"},
            {"path": "/api/cron/ecos-daily", "schedule": "0 23 * * *"},
            {
                "path": "/api/cron/recommendations-daily",
                "schedule": "10 0 * * *",
            },
        ]


def test_vercel_health_endpoint() -> None:
    request = Request({"type": "http", "method": "GET", "path": "/api/health"})

    response = asyncio.run(health(request))

    assert response.status_code == 200
    assert response.body == (
        b'{"status":"ok","service":"kospi-analyzer","runtime":"streamlit-asgi"}'
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


def test_vercel_scheduled_refresh_requires_secret() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/cron/krx-daily",
            "path_params": {"step": "krx-daily"},
            "headers": [],
        }
    )

    with patch.dict("os.environ", {}, clear=True):
        response = asyncio.run(scheduled_refresh(request))

    assert response.status_code == 401
    assert response.body == b'{"status":"unauthorized"}'


def test_vercel_scheduled_refresh_runs_authorized_step() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/cron/ecos-daily",
            "path_params": {"step": "ecos-daily"},
            "headers": [(b"authorization", b"Bearer test-secret")],
        }
    )

    with (
        patch.dict("os.environ", {"CRON_SECRET": "test-secret"}, clear=True),
        patch(
            "scripts.bootstrap_vercel.scheduled_bootstrap",
            return_value={"status": "ok", "steps": []},
        ) as run,
    ):
        response = asyncio.run(scheduled_refresh(request))

    assert response.status_code == 200
    assert response.body == b'{"status":"ok","steps":[]}'
    run.assert_called_once_with(provider="ecos-daily")
