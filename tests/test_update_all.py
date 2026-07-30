from __future__ import annotations

import subprocess
from datetime import date

from scripts.update_all import (
    _previous_weekday,
    build_steps,
    resolve_event_symbols,
    run_pipeline,
)


def test_update_all_defaults_to_previous_weekday() -> None:
    assert _previous_weekday(date(2026, 7, 30)) == date(2026, 7, 29)
    assert _previous_weekday(date(2026, 8, 3)) == date(2026, 7, 31)


def test_update_all_explicit_symbols_are_deduplicated() -> None:
    assert resolve_event_symbols(["005930", "000660", "005930"]) == [
        "005930",
        "000660",
    ]


def test_update_all_builds_provider_steps_in_dependency_order() -> None:
    steps = build_steps(
        as_of_date=date(2026, 7, 29),
        symbols=["005930", "000660"],
        ecos_days=30,
    )

    assert [step.name for step in steps] == [
        "stock_master",
        "daily_prices",
        "daily_index",
        "events_005930",
        "events_000660",
        "ecos_macro",
    ]
    assert steps[-1].arguments == (
        "--start",
        "2026-06-29",
        "--end",
        "2026-07-29",
    )


def test_update_all_reports_successful_structured_results() -> None:
    steps = build_steps(
        as_of_date=date(2026, 7, 29),
        symbols=["005930"],
        ecos_days=30,
    )

    def successful_runner(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"state":"AVAILABLE"}\n',
            stderr="",
        )

    returncode, results = run_pipeline(steps, runner=successful_runner)

    assert returncode == 0
    assert len(results) == 5
    assert all(result["state"] == "AVAILABLE" for result in results)


def test_update_all_continues_after_failure_by_default() -> None:
    steps = build_steps(
        as_of_date=date(2026, 7, 29),
        symbols=["005930"],
        ecos_days=30,
    )
    calls = 0

    def mixed_runner(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        del kwargs
        calls += 1
        return subprocess.CompletedProcess(
            command,
            1 if calls == 2 else 0,
            stdout=(
                '{"state":"FETCH_FAILED"}\n'
                if calls == 2
                else '{"state":"AVAILABLE"}\n'
            ),
            stderr="",
        )

    returncode, results = run_pipeline(steps, runner=mixed_runner)

    assert returncode == 1
    assert len(results) == len(steps)
    assert results[1]["state"] == "FETCH_FAILED"
