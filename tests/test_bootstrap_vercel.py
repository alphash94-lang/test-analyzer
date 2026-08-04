from __future__ import annotations

import asyncio
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
    assert results == [
        {"step": "universe", "state": "AVAILABLE", "returncode": 0}
    ]


def test_run_steps_rejects_unknown_step() -> None:
    with pytest.raises(ValueError, match="unknown bootstrap provider"):
        asyncio.run(
            bootstrap_vercel._run_steps(
                date(2026, 8, 3),
                only="does-not-exist",
            )
        )
