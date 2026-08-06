from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import date

import pytest

from scripts import bootstrap_vercel


def test_run_steps_executes_only_requested_normalized_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[date] = []

    async def run_universe(as_of: date) -> int:
        calls.append(as_of)
        return 0

    monkeypatch.setattr(bootstrap_vercel.update_stock_master, "_run", run_universe)
    as_of = date(2026, 8, 3)

    results = asyncio.run(bootstrap_vercel._run_steps(as_of, only="universe"))

    assert calls == [as_of]
    assert results == [{"step": "universe", "state": "AVAILABLE", "returncode": 0}]


def test_run_steps_rejects_unknown_step() -> None:
    with pytest.raises(ValueError, match="unknown bootstrap provider"):
        asyncio.run(
            bootstrap_vercel._run_steps(
                date(2026, 8, 3),
                only="does-not-exist",
            )
        )


def test_run_steps_executes_bounded_daily_krx_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, date]] = []

    async def run_step(name: str, as_of: date) -> int:
        calls.append((name, as_of))
        return 0

    monkeypatch.setattr(
        bootstrap_vercel.update_stock_master,
        "_run",
        lambda as_of: run_step("master", as_of),
    )
    monkeypatch.setattr(
        bootstrap_vercel.update_daily_prices,
        "_run",
        lambda as_of: run_step("prices", as_of),
    )
    monkeypatch.setattr(
        bootstrap_vercel.update_daily_index,
        "_run",
        lambda as_of: run_step("index", as_of),
    )
    as_of = date(2026, 8, 5)

    results = asyncio.run(bootstrap_vercel._run_steps(as_of, only="krx-daily"))

    assert calls == [
        ("master", as_of),
        ("prices", as_of),
        ("index", as_of),
    ]
    assert results == [{"step": "krx-daily", "state": "AVAILABLE", "returncode": 0}]


def test_calendar_provider_uses_current_date_not_market_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[date, int]] = []

    async def refresh_kind(
        settings: object,
        as_of: date,
        *,
        shard_index: int,
    ) -> int:
        del settings
        calls.append((as_of, shard_index))
        return 0

    monkeypatch.setattr(
        bootstrap_vercel,
        "_refresh_kind_daily",
        refresh_kind,
    )

    results = asyncio.run(
        bootstrap_vercel._run_steps(
            date(2026, 8, 7),
            only="kind-daily-2",
            calendar_date=date(2026, 8, 9),
        )
    )

    assert calls == [(date(2026, 8, 9), 2)]
    assert results[0]["state"] == "AVAILABLE"


def test_watchlist_refresh_is_split_into_ten_symbol_shards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    symbols = [f"{index:06d}" for index in range(25)]

    class FakeWatchlistService:
        def __init__(self, settings: object) -> None:
            del settings

        def symbols(self) -> list[str]:
            return symbols

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        bootstrap_vercel,
        "EventWatchlistService",
        FakeWatchlistService,
    )

    assert bootstrap_vercel._watchlist_symbols(object(), shard_index=0) == symbols[:10]
    assert bootstrap_vercel._watchlist_symbols(object(), shard_index=2) == symbols[20:]
    assert bootstrap_vercel._watchlist_symbols(object(), shard_index=3) == []


def test_scheduled_bootstrap_skips_overlapping_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def busy_lock(settings: object, step: str):
        del settings, step
        yield False

    monkeypatch.setattr(bootstrap_vercel, "_scheduled_step_lock", busy_lock)

    result = bootstrap_vercel.scheduled_bootstrap(provider="naver-daily-0")

    assert result == {"status": "busy", "step": "naver-daily-0"}
